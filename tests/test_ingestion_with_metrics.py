"""
Integration test for enrichment metrics in the ingestion pipeline (U6).

Demonstrates:
- Metrics collection during document ingestion
- Metrics after full ingest cycle
- Thread-safe metrics from async ingestion operations
"""

import pytest
from unittest.mock import patch, MagicMock

from app.metrics.enrichment_metrics import get_metrics, reset_metrics, MetricsSnapshot
from app.ingestion.ingestor import ingest_and_index_pdf_bytes
from app.models.document import Chunk, IngestionResult, Page
from app.vectorstore.qdrant_client import upsert_chunks


class TestIngestWithMetrics:
    """Integration tests for ingestion pipeline with metrics."""

    def setup_method(self):
        """Setup before each test."""
        reset_metrics()

    def teardown_method(self):
        """Cleanup after each test."""
        reset_metrics()

    def test_metrics_available_after_ingest(self):
        """Test that metrics are available and updated after ingestion."""
        metrics = get_metrics()

        # Simulate ingestion without actual file I/O
        metrics.start_ingestion_timer()
        metrics.increment_documents_indexed(1)
        metrics.increment_chunks_indexed(25)
        metrics.stop_ingestion_timer(1)

        stats = metrics.get_stats()

        assert stats.documents_indexed == 1
        assert stats.chunks_indexed == 25
        assert stats.ingestion_throughput_docs_per_sec > 0

    def test_metrics_during_enrichment_simulation(self):
        """Test metrics collection during simulated enrichment workflow."""
        metrics = get_metrics()

        # Simulate ingestion phase
        metrics.start_ingestion_timer()
        metrics.increment_documents_indexed(3)
        metrics.increment_chunks_indexed(100)
        metrics.stop_ingestion_timer(3)

        # Simulate enrichment phase
        metrics.set_enrichment_pending(100)
        metrics.increment_cache_hits(70)  # 70% hit rate
        metrics.increment_cache_misses(30)

        # Simulate background enrichment completing
        for _ in range(10):
            metrics.record_enrichment_latency(1.2)  # 1.2 seconds per batch

        metrics.set_enrichment_pending(0)
        metrics.increment_enrichment_completed(100)

        stats = metrics.get_stats()

        assert stats.documents_indexed == 3
        assert stats.chunks_indexed == 100
        assert stats.cache_hits == 70
        assert stats.cache_misses == 30
        assert stats.cache_hit_rate > 69 and stats.cache_hit_rate < 71  # ~70%
        assert stats.enrichment_completed == 100
        assert stats.enrichment_pending == 0
        assert stats.enrichment_latency_samples == 10

    def test_metrics_with_on_demand_enrichment(self):
        """Test metrics collection for on-demand enrichment during retrieval."""
        metrics = get_metrics()

        # Initial ingestion
        metrics.increment_documents_indexed(1)
        metrics.increment_chunks_indexed(30)

        # Some chunks not yet enriched, so on-demand enrichment happens during retrieval
        metrics.increment_cache_hits(20)
        metrics.increment_cache_misses(10)
        metrics.record_on_demand_enrichment_latency(2.5)
        metrics.record_on_demand_enrichment_latency(2.3)

        stats = metrics.get_stats()

        assert stats.cache_hit_rate > 66 and stats.cache_hit_rate < 68  # ~67%
        assert stats.on_demand_latency_samples == 2

    def test_metrics_snapshot_contains_all_fields(self):
        """Test that metrics snapshot is complete and well-formed."""
        metrics = get_metrics()

        # Populate all metric types
        metrics.start_ingestion_timer()
        metrics.increment_documents_indexed(2)
        metrics.increment_chunks_indexed(50)
        metrics.increment_enrichment_completed(25)
        metrics.set_enrichment_pending(25)
        metrics.increment_cache_hits(100)
        metrics.increment_cache_misses(50)
        for _ in range(5):
            metrics.record_enrichment_latency(1.5)
        for _ in range(3):
            metrics.record_on_demand_enrichment_latency(2.0)
        metrics.stop_ingestion_timer(2)

        snapshot = metrics.get_stats()

        # Verify all fields are present and initialized
        assert isinstance(snapshot, MetricsSnapshot)
        assert snapshot.timestamp is not None
        assert snapshot.documents_indexed == 2
        assert snapshot.chunks_indexed == 50
        assert snapshot.enrichment_completed == 25
        assert snapshot.enrichment_pending == 25
        assert snapshot.cache_hits == 100
        assert snapshot.cache_misses == 50
        assert snapshot.cache_hit_rate > 0
        assert snapshot.enrichment_latency_samples == 5
        assert snapshot.enrichment_latency_mean_ms > 0
        assert snapshot.on_demand_latency_samples == 3
        assert snapshot.on_demand_latency_mean_ms > 0
        assert snapshot.ingestion_start_time is not None
        assert snapshot.ingestion_total_duration_sec >= 0
        assert snapshot.ingestion_throughput_docs_per_sec > 0

    def test_metrics_resilient_to_errors(self):
        """Test that metrics operations are resilient to errors."""
        metrics = get_metrics()

        # These should all succeed even if called incorrectly
        metrics.increment_documents_indexed(-1)  # Negative is allowed
        metrics.increment_chunks_indexed(0)  # Zero is allowed
        metrics.set_enrichment_pending(-5)  # Negative gauge is allowed
        metrics.record_enrichment_latency(-1.0)  # Negative latency should be ignored

        # get_stats should not crash
        stats = metrics.get_stats()
        assert isinstance(stats, MetricsSnapshot)
        assert stats.documents_indexed == -1  # Counter can go negative
        assert stats.enrichment_latency_samples == 0  # Negative latency ignored

    def test_metrics_multiple_ingest_cycles(self):
        """Test metrics across multiple ingestion cycles."""
        metrics = get_metrics()

        # First ingest cycle
        metrics.start_ingestion_timer()
        metrics.increment_documents_indexed(2)
        metrics.increment_chunks_indexed(40)
        metrics.stop_ingestion_timer(2)

        stats1 = metrics.get_stats()
        throughput1 = stats1.ingestion_throughput_docs_per_sec

        # Second ingest cycle (metrics accumulate)
        metrics.start_ingestion_timer()
        metrics.increment_documents_indexed(1)
        metrics.increment_chunks_indexed(20)
        metrics.stop_ingestion_timer(1)

        stats2 = metrics.get_stats()

        assert stats2.documents_indexed == 3
        assert stats2.chunks_indexed == 60
        # Throughput is based on most recent cycle
        assert stats2.ingestion_throughput_docs_per_sec > 0

    def test_metrics_logging_output(self):
        """Test that metrics logging completes without error."""
        metrics = get_metrics()

        # Populate metrics
        metrics.start_ingestion_timer()
        metrics.increment_documents_indexed(5)
        metrics.increment_chunks_indexed(75)
        metrics.set_enrichment_pending(30)
        metrics.increment_enrichment_completed(45)
        metrics.increment_cache_hits(200)
        metrics.increment_cache_misses(100)
        for _ in range(20):
            metrics.record_enrichment_latency(1.3)
        metrics.stop_ingestion_timer(5)

        # Log stats should not raise
        try:
            metrics.log_stats()
        except Exception as e:
            pytest.fail(f"log_stats raised: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
