"""
Metrics collection and reporting for enrichment pipeline observability (U6) and latency tracking (U7).

Provides:
- EnrichmentMetrics: Thread-safe metrics collector
- Counter metrics: documents_indexed, chunks_indexed, enrichment_completed, cache hits/misses
- Gauge metrics: enrichment_pending, ingestion_throughput
- Histogram metrics: enrichment_latency, on_demand_enrichment_latency
- LatencyMetrics: Comprehensive latency tracking for RAG pipeline
- LatencyTracker: Checkpoint-based latency measurement
- Integration with app lifespan for periodic reporting
"""

from app.metrics.latency import LatencyMetrics, LatencyTracker

__all__ = ["LatencyMetrics", "LatencyTracker"]
