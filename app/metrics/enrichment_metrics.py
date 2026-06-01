"""
Enrichment pipeline metrics collection and reporting (U6).

Collects metrics for:
- Ingestion: documents_indexed, chunks_indexed, ingestion_throughput
- Enrichment: enrichment_completed, enrichment_pending, enrichment_latency
- Cache: cache_hits, cache_misses, cache_hit_rate
- On-demand: on_demand_enrichment_latency

Thread-safe design for concurrent access from FastAPI routes and Celery workers.
Metrics emitted to stdout via logging; optional Prometheus export (future).

Example usage:
    from app.metrics.enrichment_metrics import get_metrics

    metrics = get_metrics()
    metrics.increment_documents_indexed(1)
    metrics.increment_chunks_indexed(42)
    metrics.record_enrichment_latency(2.5)
    metrics.record_cache_hit()
    metrics.set_enrichment_pending(10)

    # View summary
    stats = metrics.get_stats()
    metrics.log_stats()  # Write to logger
"""

import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import mean, median, quantiles
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MetricsSnapshot:
    """Immutable snapshot of metrics at a point in time."""

    timestamp: str
    documents_indexed: int = 0
    chunks_indexed: int = 0
    enrichment_completed: int = 0
    enrichment_pending: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_hit_rate: float = 0.0
    enrichment_latency_samples: int = 0
    enrichment_latency_mean_ms: float = 0.0
    enrichment_latency_median_ms: float = 0.0
    enrichment_latency_p95_ms: float = 0.0
    enrichment_latency_p99_ms: float = 0.0
    on_demand_latency_samples: int = 0
    on_demand_latency_mean_ms: float = 0.0
    on_demand_latency_p95_ms: float = 0.0
    ingestion_throughput_docs_per_sec: float = 0.0
    ingestion_start_time: Optional[str] = None
    ingestion_total_duration_sec: float = 0.0


class EnrichmentMetrics:
    """
    Thread-safe metrics collector for enrichment pipeline observability.

    Tracks:
    - Counters: documents_indexed, chunks_indexed, enrichment_completed, cache hits/misses
    - Gauges: enrichment_pending, ingestion_throughput
    - Histograms: enrichment_latency, on_demand_enrichment_latency

    Design:
    - Lock-based thread safety (threading.RLock for recursive calls)
    - No blocking on metric collection failures
    - Graceful degradation if metrics unavailable
    - In-memory storage; optional export to Prometheus (future)
    """

    def __init__(self) -> None:
        """Initialize empty metrics."""
        self._lock = threading.RLock()

        # Counters
        self._documents_indexed = 0
        self._chunks_indexed = 0
        self._enrichment_completed = 0
        self._cache_hits = 0
        self._cache_misses = 0

        # Gauges
        self._enrichment_pending = 0
        self._ingestion_throughput_docs_per_sec = 0.0

        # Histograms (store all samples for statistical analysis)
        self._enrichment_latency_samples: list[float] = []
        self._on_demand_latency_samples: list[float] = []

        # Ingestion tracking
        self._ingestion_start_time: Optional[float] = None
        self._ingestion_start_timestamp: Optional[str] = None

        logger.info("Initialized enrichment metrics collector")

    def increment_documents_indexed(self, count: int = 1) -> None:
        """Increment document indexing counter."""
        try:
            with self._lock:
                self._documents_indexed += count
        except Exception as e:
            logger.warning("Failed to increment documents_indexed: %s", e)

    def increment_chunks_indexed(self, count: int) -> None:
        """Increment chunk indexing counter."""
        try:
            with self._lock:
                self._chunks_indexed += count
        except Exception as e:
            logger.warning("Failed to increment chunks_indexed: %s", e)

    def increment_enrichment_completed(self, count: int = 1) -> None:
        """Increment enrichment completed counter."""
        try:
            with self._lock:
                self._enrichment_completed += count
        except Exception as e:
            logger.warning("Failed to increment enrichment_completed: %s", e)

    def increment_cache_hits(self, count: int = 1) -> None:
        """Increment cache hit counter."""
        try:
            with self._lock:
                self._cache_hits += count
        except Exception as e:
            logger.warning("Failed to increment cache_hits: %s", e)

    def increment_cache_misses(self, count: int = 1) -> None:
        """Increment cache miss counter."""
        try:
            with self._lock:
                self._cache_misses += count
        except Exception as e:
            logger.warning("Failed to increment cache_misses: %s", e)

    def set_enrichment_pending(self, count: int) -> None:
        """Set gauge for pending enrichment tasks."""
        try:
            with self._lock:
                self._enrichment_pending = count
        except Exception as e:
            logger.warning("Failed to set enrichment_pending: %s", e)

    def record_enrichment_latency(self, latency_seconds: float) -> None:
        """Record enrichment latency sample (seconds)."""
        try:
            if latency_seconds < 0:
                logger.warning("Negative latency recorded: %f", latency_seconds)
                return
            with self._lock:
                self._enrichment_latency_samples.append(latency_seconds)
        except Exception as e:
            logger.warning("Failed to record enrichment_latency: %s", e)

    def record_on_demand_enrichment_latency(self, latency_seconds: float) -> None:
        """Record on-demand enrichment latency sample (seconds)."""
        try:
            if latency_seconds < 0:
                logger.warning("Negative on-demand latency recorded: %f", latency_seconds)
                return
            with self._lock:
                self._on_demand_latency_samples.append(latency_seconds)
        except Exception as e:
            logger.warning("Failed to record on_demand_latency: %s", e)

    def start_ingestion_timer(self) -> None:
        """Mark start of ingestion cycle for throughput calculation."""
        try:
            with self._lock:
                self._ingestion_start_time = time.time()
                self._ingestion_start_timestamp = datetime.now(timezone.utc).isoformat()
        except Exception as e:
            logger.warning("Failed to start ingestion timer: %s", e)

    def stop_ingestion_timer(self, documents_count: int) -> None:
        """
        Mark end of ingestion cycle and calculate throughput.

        Args:
            documents_count: Number of documents ingested in this cycle
        """
        try:
            with self._lock:
                if self._ingestion_start_time is None:
                    logger.warning("stop_ingestion_timer called without start_ingestion_timer")
                    return

                elapsed = time.time() - self._ingestion_start_time
                if elapsed > 0:
                    self._ingestion_throughput_docs_per_sec = documents_count / elapsed
        except Exception as e:
            logger.warning("Failed to stop ingestion timer: %s", e)

    def get_stats(self) -> MetricsSnapshot:
        """
        Return immutable snapshot of current metrics.

        Calculates summary statistics (mean, median, percentiles) for histograms.

        Returns:
            MetricsSnapshot with all current metrics
        """
        try:
            with self._lock:
                # Calculate cache hit rate
                total_cache_ops = self._cache_hits + self._cache_misses
                cache_hit_rate = (
                    (self._cache_hits / total_cache_ops * 100)
                    if total_cache_ops > 0
                    else 0.0
                )

                # Calculate enrichment latency stats (convert to ms)
                enrichment_stats = self._compute_latency_stats(
                    self._enrichment_latency_samples
                )
                on_demand_stats = self._compute_latency_stats(
                    self._on_demand_latency_samples
                )

                # Calculate total ingestion duration
                ingestion_duration = 0.0
                if (
                    self._ingestion_start_time is not None
                    and self._ingestion_start_timestamp is not None
                ):
                    ingestion_duration = time.time() - self._ingestion_start_time

                return MetricsSnapshot(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    documents_indexed=self._documents_indexed,
                    chunks_indexed=self._chunks_indexed,
                    enrichment_completed=self._enrichment_completed,
                    enrichment_pending=self._enrichment_pending,
                    cache_hits=self._cache_hits,
                    cache_misses=self._cache_misses,
                    cache_hit_rate=cache_hit_rate,
                    enrichment_latency_samples=len(self._enrichment_latency_samples),
                    enrichment_latency_mean_ms=enrichment_stats["mean"],
                    enrichment_latency_median_ms=enrichment_stats["median"],
                    enrichment_latency_p95_ms=enrichment_stats["p95"],
                    enrichment_latency_p99_ms=enrichment_stats["p99"],
                    on_demand_latency_samples=len(self._on_demand_latency_samples),
                    on_demand_latency_mean_ms=on_demand_stats["mean"],
                    on_demand_latency_p95_ms=on_demand_stats["p95"],
                    ingestion_throughput_docs_per_sec=self._ingestion_throughput_docs_per_sec,
                    ingestion_start_time=self._ingestion_start_timestamp,
                    ingestion_total_duration_sec=ingestion_duration,
                )
        except Exception as e:
            logger.error("Failed to get stats snapshot: %s", e)
            # Return empty snapshot on failure
            return MetricsSnapshot(
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

    def log_stats(self) -> None:
        """Log current metrics to stdout in human-readable format."""
        try:
            stats = self.get_stats()
            logger.info("=" * 80)
            logger.info("ENRICHMENT PIPELINE METRICS SNAPSHOT")
            logger.info("=" * 80)
            logger.info("Timestamp: %s", stats.timestamp)

            logger.info("--- Ingestion ---")
            logger.info("  Documents indexed: %d", stats.documents_indexed)
            logger.info("  Chunks indexed: %d", stats.chunks_indexed)
            if stats.ingestion_start_time:
                logger.info("  Ingestion start time: %s", stats.ingestion_start_time)
                logger.info("  Ingestion duration: %.1f seconds", stats.ingestion_total_duration_sec)
            logger.info(
                "  Ingestion throughput: %.2f docs/sec",
                stats.ingestion_throughput_docs_per_sec,
            )

            logger.info("--- Enrichment ---")
            logger.info("  Completed: %d", stats.enrichment_completed)
            logger.info("  Pending: %d", stats.enrichment_pending)
            if stats.enrichment_latency_samples > 0:
                logger.info("  Background enrichment latency samples: %d", stats.enrichment_latency_samples)
                logger.info(
                    "    Mean: %.2f ms, Median: %.2f ms, P95: %.2f ms, P99: %.2f ms",
                    stats.enrichment_latency_mean_ms,
                    stats.enrichment_latency_median_ms,
                    stats.enrichment_latency_p95_ms,
                    stats.enrichment_latency_p99_ms,
                )

            logger.info("--- Cache ---")
            logger.info("  Hits: %d, Misses: %d", stats.cache_hits, stats.cache_misses)
            logger.info("  Hit rate: %.1f%%", stats.cache_hit_rate)

            if stats.on_demand_latency_samples > 0:
                logger.info("--- On-Demand Enrichment ---")
                logger.info("  Samples: %d", stats.on_demand_latency_samples)
                logger.info(
                    "    Mean: %.2f ms, P95: %.2f ms",
                    stats.on_demand_latency_mean_ms,
                    stats.on_demand_latency_p95_ms,
                )

            logger.info("=" * 80)
        except Exception as e:
            logger.error("Failed to log metrics: %s", e)

    def reset(self) -> None:
        """Reset all metrics. Used for testing."""
        try:
            with self._lock:
                self._documents_indexed = 0
                self._chunks_indexed = 0
                self._enrichment_completed = 0
                self._enrichment_pending = 0
                self._cache_hits = 0
                self._cache_misses = 0
                self._enrichment_latency_samples.clear()
                self._on_demand_latency_samples.clear()
                self._ingestion_start_time = None
                self._ingestion_start_timestamp = None
                self._ingestion_throughput_docs_per_sec = 0.0
                logger.info("Enrichment metrics reset")
        except Exception as e:
            logger.warning("Failed to reset metrics: %s", e)

    @staticmethod
    def _compute_latency_stats(samples: list[float]) -> dict[str, float]:
        """
        Compute latency statistics from samples (seconds -> ms).

        Args:
            samples: List of latency samples in seconds

        Returns:
            Dict with keys: mean, median, p95, p99 (all in milliseconds)
        """
        if not samples:
            return {"mean": 0.0, "median": 0.0, "p95": 0.0, "p99": 0.0}

        samples_ms = [s * 1000 for s in samples]
        try:
            # Compute quantiles if we have enough samples
            if len(samples_ms) >= 20:
                quantile_values = quantiles(samples_ms, n=100)
                p95 = quantile_values[94]  # 95th percentile
                p99 = quantile_values[98]  # 99th percentile
            else:
                # For small samples, estimate from max
                p95 = max(samples_ms)
                p99 = max(samples_ms)

            return {
                "mean": mean(samples_ms),
                "median": median(samples_ms),
                "p95": p95,
                "p99": p99,
            }
        except Exception as e:
            logger.warning("Failed to compute latency stats: %s", e)
            return {"mean": 0.0, "median": 0.0, "p95": 0.0, "p99": 0.0}


# Global metrics instance (singleton)
_metrics_instance: EnrichmentMetrics | None = None


def get_metrics() -> EnrichmentMetrics:
    """
    Get or create global metrics instance.

    Uses singleton pattern: first call creates instance, subsequent calls
    return same instance. Safe for module imports across the application.

    Returns:
        EnrichmentMetrics singleton instance
    """
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = EnrichmentMetrics()
    return _metrics_instance


def reset_metrics() -> None:
    """
    Reset global metrics instance. Used for testing only.

    Clears all metrics and resets singleton.
    """
    global _metrics_instance
    if _metrics_instance is not None:
        _metrics_instance.reset()
    _metrics_instance = None
    logger.info("Reset enrichment metrics singleton")
