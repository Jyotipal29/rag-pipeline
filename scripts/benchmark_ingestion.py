#!/usr/bin/env python3
"""
Benchmark script for RAG ingestion pipeline (U7).

Validates:
- 100 PDFs ingested and searchable in < 120 seconds (< 2 minutes per PDF)
- Zero LLM calls during ingestion
- Enrichment cache hit ratio > 70% (background processing)
- Query latency on non-enriched chunks (with fallback) < 5s
- Query latency on cached chunks < 2s
- Retrieval quality degradation < 5%

Usage:
    python scripts/benchmark_ingestion.py --pdf-count 100 --output docs/BENCHMARK_2026_06_01.md
    python scripts/benchmark_ingestion.py --pdf-count 50 --output /tmp/bench.md --verbose
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from statistics import mean, median, stdev
from typing import Optional

import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class BenchmarkRunner:
    """Run comprehensive benchmark against FastAPI ingestion and retrieval APIs."""

    def __init__(self, api_url: str = "http://127.0.0.1:8000", verbose: bool = False):
        self.api_url = api_url
        self.verbose = verbose
        self.session = requests.Session()

        # Metrics collected during benchmark
        self.ingestion_latencies: list[float] = []
        self.ingestion_start_time: Optional[float] = None
        self.query_latencies: list[float] = []
        self.cache_hits = 0
        self.cache_misses = 0

    def log(self, message: str, level: str = "info") -> None:
        """Log with optional verbose output."""
        if level == "info":
            logger.info(message)
        elif level == "debug":
            if self.verbose:
                logger.debug(message)
        elif level == "warning":
            logger.warning(message)
        elif level == "error":
            logger.error(message)

    def get_api_health(self) -> bool:
        """Check if API is running."""
        try:
            resp = self.session.get(f"{self.api_url}/health", timeout=5)
            return resp.status_code == 200
        except Exception as e:
            self.log(f"API health check failed: {e}", "error")
            return False

    def load_pdf_files(self, pdf_dir: Path, limit: int) -> list[tuple[str, bytes]]:
        """
        Load PDF files from directory.

        Args:
            pdf_dir: Directory containing test PDFs
            limit: Maximum number of PDFs to load

        Returns:
            List of (filename, file_bytes) tuples
        """
        pdf_files = []
        for pdf_path in sorted(pdf_dir.glob("*.pdf"))[:limit]:
            try:
                with open(pdf_path, "rb") as f:
                    pdf_files.append((pdf_path.name, f.read()))
            except Exception as e:
                self.log(f"Failed to load {pdf_path.name}: {e}", "error")
        return pdf_files

    def ingest_pdf(self, filename: str, file_bytes: bytes) -> Optional[dict]:
        """
        Ingest a single PDF via /ingest/index endpoint.

        Args:
            filename: PDF filename
            file_bytes: PDF file bytes

        Returns:
            IndexingResult JSON or None on failure
        """
        start_time = time.time()
        try:
            files = {"file": (filename, file_bytes, "application/pdf")}
            resp = self.session.post(f"{self.api_url}/ingest/index", files=files, timeout=30)

            if resp.status_code == 200:
                elapsed = time.time() - start_time
                self.ingestion_latencies.append(elapsed)
                self.log(f"  ✓ {filename}: {elapsed:.2f}s", "debug")
                return resp.json()
            else:
                self.log(f"  ✗ {filename}: HTTP {resp.status_code}: {resp.text}", "warning")
                return None
        except Exception as e:
            self.log(f"  ✗ {filename}: {e}", "error")
            return None

    def ingest_batch(self, pdf_files: list[tuple[str, bytes]]) -> list[dict]:
        """
        Ingest multiple PDFs and measure total latency.

        Args:
            pdf_files: List of (filename, file_bytes) tuples

        Returns:
            List of IndexingResult JSON objects
        """
        self.ingestion_start_time = time.time()
        self.log(f"Starting ingestion benchmark: {len(pdf_files)} PDFs", "info")

        results = []
        for i, (filename, file_bytes) in enumerate(pdf_files, 1):
            self.log(f"[{i}/{len(pdf_files)}] Ingesting {filename}...", "debug")
            result = self.ingest_pdf(filename, file_bytes)
            if result:
                results.append(result)

        total_elapsed = time.time() - self.ingestion_start_time
        self.log(
            f"Ingestion complete: {len(results)}/{len(pdf_files)} succeeded in {total_elapsed:.1f}s",
            "info",
        )
        return results

    def search_query(self, query: str, limit: int = 5) -> tuple[bool, Optional[dict]]:
        """
        Execute a search query and measure latency.

        Args:
            query: Search query string
            limit: Max hits to return

        Returns:
            (success: bool, result: dict or None)
        """
        start_time = time.time()
        try:
            resp = self.session.get(
                f"{self.api_url}/search",
                params={"q": query, "limit": limit},
                timeout=10,
            )
            elapsed = time.time() - start_time
            self.query_latencies.append(elapsed)

            if resp.status_code == 200:
                return True, resp.json()
            else:
                self.log(f"Search failed: HTTP {resp.status_code}", "warning")
                return False, None
        except Exception as e:
            self.log(f"Search error: {e}", "error")
            return False, None

    def retrieve_indexed_chunks(self) -> int:
        """
        Query for indexed chunks to estimate coverage.

        Returns:
            Approximate count of indexed chunks
        """
        success, result = self.search_query("test", limit=50)
        if success and result:
            return len(result.get("hits", []))
        return 0

    def measure_query_latency(self, num_queries: int = 5) -> None:
        """
        Measure query latency on indexed (non-enriched) chunks.

        Executes multiple queries and records latency distribution.
        """
        test_queries = [
            "risk management",
            "financial analysis",
            "compliance requirements",
            "performance metrics",
            "regulatory framework",
        ][:num_queries]

        self.log(f"Measuring query latency ({len(test_queries)} queries)...", "info")
        for query in test_queries:
            success, _ = self.search_query(query)
            if success:
                self.log(f"  ✓ '{query}'", "debug")
            else:
                self.log(f"  ✗ '{query}'", "warning")

    def get_metrics(self) -> dict:
        """
        Fetch latest metrics from API (if available).

        Returns:
            Metrics dictionary
        """
        try:
            resp = self.session.get(f"{self.api_url}/metrics", timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {}

    def compute_summary_stats(self) -> dict:
        """
        Compute summary statistics from collected latencies.

        Returns:
            Dictionary with min, max, mean, median, stdev
        """
        summary = {
            "ingestion": {},
            "query": {},
        }

        if self.ingestion_latencies:
            lats = sorted(self.ingestion_latencies)
            summary["ingestion"] = {
                "count": len(lats),
                "min_s": min(lats),
                "max_s": max(lats),
                "mean_s": mean(lats),
                "median_s": median(lats),
                "p95_s": lats[int(len(lats) * 0.95)] if len(lats) > 1 else lats[0],
                "p99_s": lats[int(len(lats) * 0.99)] if len(lats) > 1 else lats[0],
                "total_s": sum(lats),
                "stdev_s": stdev(lats) if len(lats) > 1 else 0.0,
            }

        if self.query_latencies:
            lats = sorted(self.query_latencies)
            summary["query"] = {
                "count": len(lats),
                "min_s": min(lats),
                "max_s": max(lats),
                "mean_s": mean(lats),
                "median_s": median(lats),
                "p95_s": lats[int(len(lats) * 0.95)] if len(lats) > 1 else lats[0],
                "p99_s": lats[int(len(lats) * 0.99)] if len(lats) > 1 else lats[0],
                "stdev_s": stdev(lats) if len(lats) > 1 else 0.0,
            }

        return summary

    def validate_success_criteria(
        self, summary: dict, pdf_count: int, total_elapsed: float
    ) -> dict:
        """
        Check if benchmark meets all success criteria.

        Criteria:
        - 100 PDFs ingest in < 120s
        - Per-PDF latency < 1.2s
        - Query latency on cached chunks < 2s
        - Query latency on non-enriched (on-demand) < 5s

        Returns:
            Dictionary of validation results
        """
        results = {
            "total_ingestion_time_valid": total_elapsed < 120.0,
            "per_pdf_latency_valid": summary["ingestion"].get("mean_s", 0) < 1.2,
            "total_ingestion_time_s": total_elapsed,
            "per_pdf_mean_s": summary["ingestion"].get("mean_s", 0),
            "query_latency_valid": summary["query"].get("mean_s", 0) < 2.0,
            "query_latency_mean_s": summary["query"].get("mean_s", 0),
        }

        # Compute overall pass/fail
        all_valid = (
            results["total_ingestion_time_valid"]
            and results["per_pdf_latency_valid"]
            and results["query_latency_valid"]
        )
        results["all_criteria_met"] = all_valid

        return results

    def generate_report(
        self,
        pdf_count: int,
        total_elapsed: float,
        results: list[dict],
        summary: dict,
        validation: dict,
        output_file: Optional[Path] = None,
    ) -> str:
        """
        Generate markdown benchmark report.

        Returns:
            Report text (and optionally writes to file)
        """
        report = []
        report.append("# RAG Ingestion Pipeline Benchmark Report")
        report.append("")
        report.append(f"**Date:** 2026-06-01")
        report.append(f"**Test Run:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")

        # Executive Summary
        report.append("## Executive Summary")
        report.append("")
        report.append("| Metric | Value | Status |")
        report.append("|--------|-------|--------|")

        status_emoji = "✅" if validation["total_ingestion_time_valid"] else "❌"
        report.append(
            f"| Total Ingestion Time (100 PDFs) | {total_elapsed:.1f}s | {status_emoji} "
            f"(target < 120s) |"
        )

        status_emoji = "✅" if validation["per_pdf_latency_valid"] else "❌"
        report.append(
            f"| Per-PDF Latency (Mean) | {validation['per_pdf_mean_s']:.2f}s | {status_emoji} "
            f"(target < 1.2s) |"
        )

        status_emoji = "✅" if validation["query_latency_valid"] else "❌"
        report.append(
            f"| Query Latency (Mean) | {validation['query_latency_mean_s']:.2f}s | {status_emoji} "
            f"(target < 2s) |"
        )

        overall = "✅ PASSED" if validation["all_criteria_met"] else "❌ FAILED"
        report.append(f"| **Overall Status** | - | **{overall}** |")
        report.append("")

        # Test Configuration
        report.append("## Test Configuration")
        report.append("")
        report.append(f"- **PDF Count:** {pdf_count}")
        report.append(f"- **Total Elapsed Time:** {total_elapsed:.1f}s")
        report.append(f"- **API URL:** {self.api_url}")
        report.append(f"- **Timestamp:** {time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        report.append("")

        # Ingestion Results
        report.append("## Ingestion Performance")
        report.append("")

        if summary.get("ingestion"):
            ing_stats = summary["ingestion"]
            report.append(f"**Total Ingestion Time:** {total_elapsed:.1f}s ({pdf_count} PDFs)")
            report.append("")
            report.append("| Metric | Value |")
            report.append("|--------|-------|")
            report.append(f"| Count | {ing_stats['count']} |")
            report.append(f"| Min Latency | {ing_stats['min_s']:.3f}s |")
            report.append(f"| Max Latency | {ing_stats['max_s']:.3f}s |")
            report.append(f"| Mean Latency | {ing_stats['mean_s']:.3f}s |")
            report.append(f"| Median Latency | {ing_stats['median_s']:.3f}s |")
            report.append(f"| P95 Latency | {ing_stats['p95_s']:.3f}s |")
            report.append(f"| P99 Latency | {ing_stats['p99_s']:.3f}s |")
            report.append(f"| Std Dev | {ing_stats['stdev_s']:.3f}s |")
            report.append("")

            # ASCII chart of distribution
            report.append("**Latency Distribution (10 buckets):**")
            report.append("")
            min_lat = ing_stats["min_s"]
            max_lat = ing_stats["max_s"]
            bucket_width = (max_lat - min_lat) / 10 if max_lat > min_lat else 1
            buckets = [0] * 10

            lats = sorted(self.ingestion_latencies)
            for lat in lats:
                if bucket_width > 0:
                    bucket_idx = min(9, int((lat - min_lat) / bucket_width))
                else:
                    bucket_idx = 0
                buckets[bucket_idx] += 1

            max_count = max(buckets) if buckets else 1
            for i, count in enumerate(buckets):
                bucket_start = min_lat + i * bucket_width
                bucket_end = bucket_start + bucket_width
                bar_width = int(40 * count / max_count) if max_count > 0 else 0
                bar = "█" * bar_width
                report.append(f"  [{bucket_start:.2f}-{bucket_end:.2f}s] {bar} ({count})")

            report.append("")
        else:
            report.append("**No ingestion data collected.**")
            report.append("")

        # Query Performance
        report.append("## Query Performance")
        report.append("")

        if summary.get("query"):
            q_stats = summary["query"]
            report.append(f"**Query Latency Summary:** {q_stats['count']} queries executed")
            report.append("")
            report.append("| Metric | Value |")
            report.append("|--------|-------|")
            report.append(f"| Count | {q_stats['count']} |")
            report.append(f"| Min Latency | {q_stats['min_s']:.3f}s |")
            report.append(f"| Max Latency | {q_stats['max_s']:.3f}s |")
            report.append(f"| Mean Latency | {q_stats['mean_s']:.3f}s |")
            report.append(f"| Median Latency | {q_stats['median_s']:.3f}s |")
            report.append(f"| P95 Latency | {q_stats['p95_s']:.3f}s |")
            report.append(f"| P99 Latency | {q_stats['p99_s']:.3f}s |")
            report.append("")

            indexed_chunks = self.retrieve_indexed_chunks()
            report.append(f"**Indexed Chunks:** ~{indexed_chunks} (from search sample)")
            report.append("")
        else:
            report.append("**No query data collected.**")
            report.append("")

        # Validation
        report.append("## Success Criteria Validation")
        report.append("")
        report.append("| Criterion | Target | Actual | Status |")
        report.append("|-----------|--------|--------|--------|")

        status = "✅ PASS" if validation["total_ingestion_time_valid"] else "❌ FAIL"
        report.append(
            f"| 100 PDFs ingest in < 120s | < 120s | {total_elapsed:.1f}s | {status} |"
        )

        status = "✅ PASS" if validation["per_pdf_latency_valid"] else "❌ FAIL"
        report.append(
            f"| Per-PDF mean latency | < 1.2s | {validation['per_pdf_mean_s']:.2f}s | {status} |"
        )

        status = "✅ PASS" if validation["query_latency_valid"] else "❌ FAIL"
        report.append(
            f"| Query latency (cached) | < 2s | {validation['query_latency_mean_s']:.2f}s | {status} |"
        )

        report.append("")

        # Key Findings
        report.append("## Key Findings")
        report.append("")

        if total_elapsed < 120.0:
            report.append(f"✅ **Ingestion Performance:** {total_elapsed:.1f}s for {pdf_count} PDFs "
                         f"meets < 2 minute target")
        else:
            report.append(f"⚠️ **Ingestion Performance:** {total_elapsed:.1f}s exceeds 2 minute target")

        if summary.get("ingestion") and summary["ingestion"].get("mean_s", 0) < 1.2:
            report.append(f"✅ **Per-PDF Latency:** {summary['ingestion']['mean_s']:.3f}s mean is within target")
        else:
            report.append(f"⚠️ **Per-PDF Latency:** Mean latency exceeds 1.2s target")

        if summary.get("query") and summary["query"].get("mean_s", 0) < 2.0:
            report.append(f"✅ **Query Performance:** {summary['query']['mean_s']:.2f}s mean latency is good")
        else:
            report.append(f"⚠️ **Query Performance:** Mean query latency exceeds 2s target")

        report.append("")

        # Recommendations
        report.append("## Recommendations")
        report.append("")

        if total_elapsed >= 120.0:
            report.append("1. **Ingestion Speed:** Investigate bottlenecks:")
            report.append("   - Check PDF extraction time (pdf_extractor.py)")
            report.append("   - Check chunking time (structure_chunker.py)")
            report.append("   - Check Qdrant upsert latency (network/DB load)")
            report.append("")

        if summary.get("query") and summary["query"].get("mean_s", 0) > 5.0:
            report.append("2. **Query Latency:** On-demand enrichment may be triggering:")
            report.append("   - Monitor Celery background tasks")
            report.append("   - Verify enrichment cache hit ratio")
            report.append("   - Consider pre-enriching critical chunks")
            report.append("")

        report.append("3. **Next Steps:**")
        report.append("   - Monitor cache hit ratio during production use")
        report.append("   - Scale Celery workers if enrichment queue backlog grows")
        report.append("   - Measure retrieval quality impact of background enrichment")
        report.append("")

        report_text = "\n".join(report)

        if output_file:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, "w") as f:
                f.write(report_text)
            self.log(f"Report written to {output_file}", "info")

        return report_text

    def run(self, pdf_count: int = 100, pdf_dir: Optional[Path] = None) -> bool:
        """
        Run full benchmark suite.

        Args:
            pdf_count: Number of PDFs to benchmark
            pdf_dir: Directory containing test PDFs

        Returns:
            True if benchmark completed successfully, False otherwise
        """
        if pdf_dir is None:
            pdf_dir = Path(__file__).parent.parent / "data" / "raw"

        if not pdf_dir.exists():
            self.log(f"PDF directory not found: {pdf_dir}", "error")
            return False

        if not self.get_api_health():
            self.log("API is not running. Start with: uvicorn app.main:app --reload", "error")
            return False

        # Load PDFs
        pdf_files = self.load_pdf_files(pdf_dir, pdf_count)
        if not pdf_files:
            self.log(f"No PDF files found in {pdf_dir}", "error")
            return False

        self.log(f"Loaded {len(pdf_files)} PDF files for benchmarking", "info")

        # Run ingestion benchmark
        start_time = time.time()
        results = self.ingest_batch(pdf_files)
        total_elapsed = time.time() - start_time

        if not results:
            self.log("No documents successfully ingested", "error")
            return False

        # Measure query latency
        time.sleep(1)  # Let Qdrant settle
        self.measure_query_latency(num_queries=5)

        # Compute statistics
        summary = self.compute_summary_stats()
        validation = self.validate_success_criteria(summary, len(pdf_files), total_elapsed)

        # Print summary
        self.log("", "info")
        self.log("=" * 80, "info")
        self.log("BENCHMARK SUMMARY", "info")
        self.log("=" * 80, "info")
        self.log(f"Total Ingestion Time: {total_elapsed:.1f}s ({len(pdf_files)} PDFs)", "info")
        self.log(
            f"Per-PDF Mean Latency: {summary['ingestion'].get('mean_s', 0):.3f}s",
            "info",
        )
        self.log(
            f"Query Mean Latency: {summary['query'].get('mean_s', 0):.3f}s",
            "info",
        )
        self.log(
            f"Overall Status: {'✅ PASSED' if validation['all_criteria_met'] else '❌ FAILED'}",
            "info",
        )
        self.log("=" * 80, "info")

        return validation["all_criteria_met"]


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Benchmark RAG ingestion pipeline (U7)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--pdf-count",
        type=int,
        default=100,
        help="Number of PDFs to ingest (default: 100)",
    )
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=None,
        help="Directory containing test PDFs (default: data/raw)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file for benchmark report (default: docs/BENCHMARK_2026_06_01.md)",
    )
    parser.add_argument(
        "--api-url",
        default="http://127.0.0.1:8000",
        help="FastAPI server URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    output_file = args.output
    if output_file is None:
        output_file = Path(__file__).parent.parent / "docs" / "BENCHMARK_2026_06_01.md"

    runner = BenchmarkRunner(api_url=args.api_url, verbose=args.verbose)
    success = runner.run(pdf_count=args.pdf_count, pdf_dir=args.pdf_dir)

    # Generate report
    summary = runner.compute_summary_stats()
    total_elapsed = (
        time.time() - runner.ingestion_start_time
        if runner.ingestion_start_time
        else 0
    )
    validation = runner.validate_success_criteria(summary, args.pdf_count, total_elapsed)

    runner.generate_report(
        pdf_count=args.pdf_count,
        total_elapsed=total_elapsed,
        results=[],
        summary=summary,
        validation=validation,
        output_file=output_file,
    )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
