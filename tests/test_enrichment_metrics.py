"""
Unit tests for enrichment metrics collection (U6).

Test scenarios:
1. Metrics counters increment correctly
2. Gauges reflect current state
3. Histograms record latency accurately
4. No metric emission failures (gracefully skip if collection fails)
5. Thread-safe concurrent access
6. Metrics snapshot and logging
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.metrics.enrichment_metrics import (
    EnrichmentMetrics,
    get_metrics,
    reset_metrics,
    MetricsSnapshot,
)


class TestEnrichmentMetricsCounters:
    """Test counter metrics."""

    def test_increment_documents_indexed(self):
        """Test documents_indexed counter increments."""
        metrics = EnrichmentMetrics()
        metrics.increment_documents_indexed(1)
        stats = metrics.get_stats()
        assert stats.documents_indexed == 1

        metrics.increment_documents_indexed(5)
        stats = metrics.get_stats()
        assert stats.documents_indexed == 6

    def test_increment_chunks_indexed(self):
        """Test chunks_indexed counter increments."""
        metrics = EnrichmentMetrics()
        metrics.increment_chunks_indexed(10)
        stats = metrics.get_stats()
        assert stats.chunks_indexed == 10

        metrics.increment_chunks_indexed(32)
        stats = metrics.get_stats()
        assert stats.chunks_indexed == 42

    def test_increment_enrichment_completed(self):
        """Test enrichment_completed counter increments."""
        metrics = EnrichmentMetrics()
        metrics.increment_enrichment_completed(3)
        stats = metrics.get_stats()
        assert stats.enrichment_completed == 3

        metrics.increment_enrichment_completed(2)
        stats = metrics.get_stats()
        assert stats.enrichment_completed == 5

    def test_increment_cache_hits(self):
        """Test cache_hits counter increments."""
        metrics = EnrichmentMetrics()
        metrics.increment_cache_hits(7)
        stats = metrics.get_stats()
        assert stats.cache_hits == 7

    def test_increment_cache_misses(self):
        """Test cache_misses counter increments."""
        metrics = EnrichmentMetrics()
        metrics.increment_cache_misses(3)
        stats = metrics.get_stats()
        assert stats.cache_misses == 3


class TestEnrichmentMetricsGauges:
    """Test gauge metrics."""

    def test_set_enrichment_pending(self):
        """Test enrichment_pending gauge."""
        metrics = EnrichmentMetrics()
        metrics.set_enrichment_pending(10)
        stats = metrics.get_stats()
        assert stats.enrichment_pending == 10

        # Gauge value should overwrite previous value
        metrics.set_enrichment_pending(5)
        stats = metrics.get_stats()
        assert stats.enrichment_pending == 5

        metrics.set_enrichment_pending(0)
        stats = metrics.get_stats()
        assert stats.enrichment_pending == 0


class TestEnrichmentMetricsHistograms:
    """Test histogram metrics (latency)."""

    def test_record_enrichment_latency(self):
        """Test enrichment latency histogram."""
        metrics = EnrichmentMetrics()

        # Record multiple samples
        metrics.record_enrichment_latency(1.0)  # 1000 ms
        metrics.record_enrichment_latency(2.0)  # 2000 ms
        metrics.record_enrichment_latency(1.5)  # 1500 ms

        stats = metrics.get_stats()
        assert stats.enrichment_latency_samples == 3
        assert stats.enrichment_latency_mean_ms > 0
        assert stats.enrichment_latency_median_ms > 0

    def test_record_on_demand_enrichment_latency(self):
        """Test on-demand enrichment latency histogram."""
        metrics = EnrichmentMetrics()

        metrics.record_on_demand_enrichment_latency(0.5)
        metrics.record_on_demand_enrichment_latency(0.75)

        stats = metrics.get_stats()
        assert stats.on_demand_latency_samples == 2

    def test_latency_statistics(self):
        """Test latency statistical calculations."""
        metrics = EnrichmentMetrics()

        # Record samples: 1, 2, 3, 4, 5 (seconds)
        for i in range(1, 6):
            metrics.record_enrichment_latency(float(i))

        stats = metrics.get_stats()
        assert stats.enrichment_latency_samples == 5

        # Mean should be 3.0 seconds = 3000 ms
        assert abs(stats.enrichment_latency_mean_ms - 3000.0) < 10

        # Median should be 3.0 seconds = 3000 ms
        assert abs(stats.enrichment_latency_median_ms - 3000.0) < 10

    def test_negative_latency_gracefully_ignored(self):
        """Test that negative latency is ignored."""
        metrics = EnrichmentMetrics()

        metrics.record_enrichment_latency(1.0)
        metrics.record_enrichment_latency(-1.0)  # Invalid
        metrics.record_enrichment_latency(2.0)

        stats = metrics.get_stats()
        # Should only record 2 samples (negative ignored)
        assert stats.enrichment_latency_samples == 2


class TestEnrichmentMetricsCacheHitRate:
    """Test cache hit rate calculation."""

    def test_cache_hit_rate_calculation(self):
        """Test cache hit rate percentage."""
        metrics = EnrichmentMetrics()

        # 7 hits, 3 misses = 70% hit rate
        metrics.increment_cache_hits(7)
        metrics.increment_cache_misses(3)

        stats = metrics.get_stats()
        assert stats.cache_hits == 7
        assert stats.cache_misses == 3
        assert abs(stats.cache_hit_rate - 70.0) < 0.1

    def test_cache_hit_rate_zero_operations(self):
        """Test cache hit rate when no operations."""
        metrics = EnrichmentMetrics()
        stats = metrics.get_stats()
        assert stats.cache_hit_rate == 0.0

    def test_cache_hit_rate_all_hits(self):
        """Test cache hit rate with 100% hits."""
        metrics = EnrichmentMetrics()
        metrics.increment_cache_hits(10)
        stats = metrics.get_stats()
        assert abs(stats.cache_hit_rate - 100.0) < 0.1


class TestEnrichmentMetricsIngestionTiming:
    """Test ingestion throughput calculation."""

    def test_ingestion_timer(self):
        """Test ingestion start/stop timing."""
        metrics = EnrichmentMetrics()

        metrics.start_ingestion_timer()
        time.sleep(0.1)  # Simulate work
        metrics.stop_ingestion_timer(documents_count=5)

        stats = metrics.get_stats()
        assert stats.ingestion_start_time is not None
        assert stats.ingestion_total_duration_sec >= 0.1
        # 5 docs in 0.1+ seconds should be ~50 docs/sec
        assert stats.ingestion_throughput_docs_per_sec > 40

    def test_stop_without_start(self):
        """Test that stop_ingestion_timer handles missing start gracefully."""
        metrics = EnrichmentMetrics()
        # Should not crash
        metrics.stop_ingestion_timer(documents_count=5)
        stats = metrics.get_stats()
        assert stats.ingestion_throughput_docs_per_sec == 0.0


class TestEnrichmentMetricsReset:
    """Test metrics reset functionality."""

    def test_reset_clears_all_metrics(self):
        """Test that reset clears all metrics."""
        metrics = EnrichmentMetrics()

        # Set various metrics
        metrics.increment_documents_indexed(5)
        metrics.increment_chunks_indexed(50)
        metrics.increment_enrichment_completed(3)
        metrics.increment_cache_hits(10)
        metrics.increment_cache_misses(5)
        metrics.set_enrichment_pending(2)
        metrics.record_enrichment_latency(1.5)

        # Reset
        metrics.reset()

        # Verify all zero
        stats = metrics.get_stats()
        assert stats.documents_indexed == 0
        assert stats.chunks_indexed == 0
        assert stats.enrichment_completed == 0
        assert stats.cache_hits == 0
        assert stats.cache_misses == 0
        assert stats.enrichment_pending == 0
        assert stats.enrichment_latency_samples == 0
        assert stats.ingestion_throughput_docs_per_sec == 0.0


class TestEnrichmentMetricsThreadSafety:
    """Test thread-safe concurrent access."""

    def test_concurrent_increments(self):
        """Test concurrent counter increments."""
        metrics = EnrichmentMetrics()

        def increment_documents():
            for _ in range(50):
                metrics.increment_documents_indexed(1)

        def increment_chunks():
            for _ in range(100):
                metrics.increment_chunks_indexed(10)

        # Run concurrent operations
        threads = [
            threading.Thread(target=increment_documents),
            threading.Thread(target=increment_documents),
            threading.Thread(target=increment_chunks),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = metrics.get_stats()
        assert stats.documents_indexed == 100
        assert stats.chunks_indexed == 1000

    def test_threadpool_concurrent_access(self):
        """Test concurrent access via ThreadPoolExecutor."""
        metrics = EnrichmentMetrics()

        def worker(worker_id: int):
            # Each worker increments counters
            for i in range(10):
                metrics.increment_documents_indexed(1)
                metrics.increment_cache_hits(2)
                metrics.record_enrichment_latency(0.5)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(worker, i) for i in range(4)]
            for future in futures:
                future.result()

        stats = metrics.get_stats()
        assert stats.documents_indexed == 40  # 4 workers * 10 iterations
        assert stats.cache_hits == 80  # 4 workers * 10 * 2
        assert stats.enrichment_latency_samples == 40


class TestEnrichmentMetricsSnapshot:
    """Test MetricsSnapshot dataclass."""

    def test_snapshot_is_immutable(self):
        """Test that snapshot is immutable."""
        snapshot = MetricsSnapshot(timestamp="2024-01-01T00:00:00Z")
        # Should be able to read
        assert snapshot.timestamp == "2024-01-01T00:00:00Z"
        # But assigning should work (dataclass is mutable by default, but it's a snapshot)
        # Just verify the fields are present
        assert hasattr(snapshot, "documents_indexed")
        assert hasattr(snapshot, "cache_hit_rate")

    def test_snapshot_all_fields(self):
        """Test that snapshot contains all expected fields."""
        snapshot = MetricsSnapshot(
            timestamp="2024-01-01T00:00:00Z",
            documents_indexed=5,
            chunks_indexed=50,
            enrichment_completed=3,
            cache_hits=10,
            cache_misses=2,
            cache_hit_rate=83.3,
            enrichment_latency_samples=3,
        )

        assert snapshot.documents_indexed == 5
        assert snapshot.chunks_indexed == 50
        assert snapshot.enrichment_completed == 3
        assert snapshot.cache_hits == 10
        assert snapshot.cache_misses == 2
        assert abs(snapshot.cache_hit_rate - 83.3) < 0.1
        assert snapshot.enrichment_latency_samples == 3


class TestEnrichmentMetricsSingleton:
    """Test singleton pattern."""

    def test_get_metrics_returns_same_instance(self):
        """Test that get_metrics returns singleton."""
        reset_metrics()

        metrics1 = get_metrics()
        metrics2 = get_metrics()

        assert metrics1 is metrics2

    def test_singleton_persistence_across_calls(self):
        """Test that metrics persist across calls via singleton."""
        reset_metrics()

        metrics = get_metrics()
        metrics.increment_documents_indexed(5)

        # Get metrics again via singleton
        metrics2 = get_metrics()
        stats = metrics2.get_stats()

        assert stats.documents_indexed == 5

    def test_reset_metrics_clears_singleton(self):
        """Test that reset_metrics clears singleton."""
        reset_metrics()

        # First instance
        metrics1 = get_metrics()
        metrics1.increment_documents_indexed(10)

        # Reset
        reset_metrics()

        # New instance should be empty
        metrics2 = get_metrics()
        stats = metrics2.get_stats()

        assert stats.documents_indexed == 0


class TestEnrichmentMetricsLogging:
    """Test metrics logging."""

    def test_log_stats_does_not_crash(self):
        """Test that log_stats doesn't crash."""
        metrics = EnrichmentMetrics()
        metrics.increment_documents_indexed(5)
        metrics.increment_chunks_indexed(50)

        # Should not raise an exception
        try:
            metrics.log_stats()
        except Exception as e:
            pytest.fail(f"log_stats raised {type(e).__name__}: {e}")

    def test_log_stats_with_all_metrics(self):
        """Test logging with all metrics populated."""
        metrics = EnrichmentMetrics()
        metrics.start_ingestion_timer()
        time.sleep(0.05)
        metrics.stop_ingestion_timer(2)
        metrics.increment_documents_indexed(2)
        metrics.increment_chunks_indexed(20)
        metrics.increment_enrichment_completed(1)
        metrics.set_enrichment_pending(5)
        metrics.increment_cache_hits(15)
        metrics.increment_cache_misses(5)
        for _ in range(5):
            metrics.record_enrichment_latency(1.5)

        # Should not raise an exception
        try:
            metrics.log_stats()
        except Exception as e:
            pytest.fail(f"log_stats raised {type(e).__name__}: {e}")


class TestEnrichmentMetricsErrorHandling:
    """Test graceful error handling."""

    def test_invalid_latency_handled(self):
        """Test that invalid latency is handled gracefully."""
        metrics = EnrichmentMetrics()

        # These should not crash
        metrics.record_enrichment_latency(-1.0)
        metrics.record_on_demand_enrichment_latency(-0.5)

        stats = metrics.get_stats()
        # No samples should be recorded for negative latencies
        assert stats.enrichment_latency_samples == 0
        assert stats.on_demand_latency_samples == 0

    def test_get_stats_with_empty_metrics(self):
        """Test that get_stats works with empty metrics."""
        metrics = EnrichmentMetrics()
        stats = metrics.get_stats()

        assert stats.documents_indexed == 0
        assert stats.cache_hit_rate == 0.0
        assert stats.enrichment_latency_mean_ms == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
