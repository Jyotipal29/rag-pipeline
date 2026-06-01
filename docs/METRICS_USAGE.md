# Enrichment Pipeline Metrics (U6)

## Overview

The enrichment pipeline includes comprehensive metrics collection for observability of ingestion, enrichment, caching, and on-demand enrichment operations. Metrics are emitted to stdout via Python logging and can optionally be exported to Prometheus.

## Architecture

### Components

- **EnrichmentMetrics**: Thread-safe metrics collector with counters, gauges, and histograms
- **Singleton pattern**: Global `get_metrics()` accessor for easy integration across modules
- **Non-blocking**: Metrics collection failures never block the ingestion pipeline
- **Logging-based**: Human-readable metrics logged to stdout at INFO level

### Metric Types

#### Counters (Monotonically increasing)
- `documents_indexed`: Total documents ingested
- `chunks_indexed`: Total chunks created
- `enrichment_completed`: Total chunks enriched (background)
- `cache_hits`: Content hash cache hits
- `cache_misses`: Content hash cache misses

#### Gauges (Point-in-time values)
- `enrichment_pending`: Current number of chunks awaiting enrichment
- `ingestion_throughput_docs_per_sec`: Docs per second in current ingestion cycle

#### Histograms (Distribution of latencies)
- `enrichment_latency_seconds`: Background enrichment batch latency (samples, mean, median, p95, p99)
- `on_demand_enrichment_latency_seconds`: On-demand enrichment during retrieval (samples, mean, p95)

## Usage Patterns

### Basic Counter Increments

```python
from app.metrics.enrichment_metrics import get_metrics

metrics = get_metrics()

# During ingestion
metrics.increment_documents_indexed(1)
metrics.increment_chunks_indexed(42)

# After enrichment completes
metrics.increment_enrichment_completed(42)

# During cache operations
metrics.increment_cache_hits(10)
metrics.increment_cache_misses(3)
```

### Gauges

```python
metrics = get_metrics()

# Track pending enrichment work
metrics.set_enrichment_pending(100)  # 100 chunks waiting
# ... enrichment happens ...
metrics.set_enrichment_pending(50)   # Progress update
```

### Latency Tracking

```python
import time

metrics = get_metrics()

# Background enrichment latency
start = time.time()
# ... enrich batch of chunks ...
duration = time.time() - start
metrics.record_enrichment_latency(duration)

# On-demand enrichment during retrieval
start = time.time()
# ... enrich chunks for current query ...
duration = time.time() - start
metrics.record_on_demand_enrichment_latency(duration)
```

### Ingestion Throughput Tracking

```python
metrics = get_metrics()

# Start ingestion cycle
metrics.start_ingestion_timer()

# Process documents
for doc in documents:
    # ... ingest doc ...
    metrics.increment_documents_indexed(1)
    metrics.increment_chunks_indexed(doc.chunk_count)

# Complete cycle
metrics.stop_ingestion_timer(documents_count=len(documents))

# Check throughput
stats = metrics.get_stats()
print(f"Throughput: {stats.ingestion_throughput_docs_per_sec:.2f} docs/sec")
```

### Retrieving Metrics

```python
metrics = get_metrics()

# Get snapshot of current metrics
stats = metrics.get_stats()

print(f"Documents indexed: {stats.documents_indexed}")
print(f"Chunks indexed: {stats.chunks_indexed}")
print(f"Cache hit rate: {stats.cache_hit_rate:.1f}%")
print(f"Enrichment latency (p95): {stats.enrichment_latency_p95_ms:.2f} ms")

# Log formatted metrics
metrics.log_stats()  # Outputs comprehensive metrics report
```

## Output Examples

### Typical Metrics Log

```
================================================================================
ENRICHMENT PIPELINE METRICS SNAPSHOT
================================================================================
Timestamp: 2026-06-01T12:00:00Z

--- Ingestion ---
  Documents indexed: 100
  Chunks indexed: 2500
  Ingestion start time: 2026-06-01T11:58:00Z
  Ingestion duration: 120.5 seconds
  Ingestion throughput: 0.83 docs/sec

--- Enrichment ---
  Completed: 2350
  Pending: 150
  Background enrichment latency samples: 150
    Mean: 1250.50 ms, Median: 1200.00 ms, P95: 1800.00 ms, P99: 2100.00 ms

--- Cache ---
  Hits: 1850, Misses: 500
  Hit rate: 78.7%

--- On-Demand Enrichment ---
  Samples: 8
    Mean: 2500.00 ms, P95: 3000.00 ms
================================================================================
```

## Integration with Ingestion Pipeline

### In `ingest_and_index_pdf_bytes()` Function

```python
from app.metrics.enrichment_metrics import get_metrics

def ingest_and_index_pdf_bytes(file_bytes: bytes, filename: str) -> IndexingResult:
    metrics = get_metrics()
    
    # ... extract and chunk ...
    
    chunks = build_chunks_for_document(...)
    metrics.increment_chunks_indexed(len(chunks))
    
    # ... index to Qdrant ...
    
    metrics.increment_documents_indexed(1)
    
    # ... enqueue enrichment task ...
    
    return IndexingResult(...)
```

### In Celery Enrichment Tasks

```python
from app.metrics.enrichment_metrics import get_metrics
import time

@celery.task
def enrich_document_task(document_id: str, chunks: list[Chunk]):
    metrics = get_metrics()
    metrics.set_enrichment_pending(len(chunks))
    
    try:
        for chunk in chunks:
            start = time.time()
            enriched = enrich_chunk(chunk)
            duration = time.time() - start
            metrics.record_enrichment_latency(duration)
            
            metrics.increment_enrichment_completed(1)
        
        metrics.set_enrichment_pending(0)
    except Exception as e:
        logger.error(f"Enrichment failed: {e}")
```

### In Retrieval On-Demand Enrichment

```python
from app.metrics.enrichment_metrics import get_metrics
import time

async def enrich_retrieved_chunks_if_needed(chunks: list[Chunk]):
    metrics = get_metrics()
    
    to_enrich = [c for c in chunks if c.enrichment_status != "COMPLETED"]
    
    if not to_enrich:
        return chunks
    
    start = time.time()
    
    for chunk in to_enrich:
        # Check cache first
        cached = cache.get(chunk.content_hash)
        if cached:
            metrics.increment_cache_hits(1)
            chunk.summary = cached.summary
            chunk.topics = cached.topics
        else:
            metrics.increment_cache_misses(1)
            # On-demand enrich
            enriched = await llm_enrich_chunk(chunk)
            chunk.summary = enriched.summary
            chunk.topics = enriched.topics
        
        chunk.enrichment_status = "COMPLETED"
    
    duration = time.time() - start
    metrics.record_on_demand_enrichment_latency(duration)
    
    return chunks
```

## Testing

### Unit Tests

Use the test classes in `tests/test_enrichment_metrics.py`:

```python
from app.metrics.enrichment_metrics import EnrichmentMetrics, reset_metrics

def test_ingestion_metrics():
    reset_metrics()
    metrics = EnrichmentMetrics()
    
    metrics.increment_documents_indexed(5)
    metrics.increment_chunks_indexed(100)
    
    stats = metrics.get_stats()
    assert stats.documents_indexed == 5
    assert stats.chunks_indexed == 100
```

### Integration Tests

See `tests/test_ingestion_with_metrics.py` for full workflow examples:

```python
def test_metrics_during_enrichment_simulation():
    """Simulate full ingest -> enrich -> retrieve workflow."""
    reset_metrics()
    metrics = get_metrics()
    
    # Ingest phase
    metrics.start_ingestion_timer()
    metrics.increment_documents_indexed(10)
    metrics.increment_chunks_indexed(300)
    metrics.stop_ingestion_timer(10)
    
    # Enrichment phase
    metrics.set_enrichment_pending(300)
    # ... enrichment happens ...
    metrics.increment_enrichment_completed(300)
    metrics.set_enrichment_pending(0)
    
    # Verify
    stats = metrics.get_stats()
    assert stats.documents_indexed == 10
    assert stats.chunks_indexed == 300
    assert stats.enrichment_completed == 300
```

## Performance Considerations

### Thread Safety
- Metrics use `threading.RLock` for concurrent access
- Safe for FastAPI (async per-request) + Celery workers (separate processes)
- No GIL contention for simple counter increments

### Memory Usage
- Histograms store all latency samples in-memory
- For 10,000+ samples, consider periodic reset or aggregation
- Current design suitable for < 100k samples per process

### Overhead
- Counter increments: < 1 microsecond
- Latency recording: < 5 microseconds
- Snapshot generation: < 10 milliseconds
- Logging output: < 50 milliseconds

## Future Enhancements

### Prometheus Export
Add optional Prometheus exporter for metrics scraping:

```python
from prometheus_client import Counter, Gauge, Histogram, generate_latest

# Create Prometheus-compatible metrics
doc_counter = Counter('enrichment_documents_indexed_total', ...)
chunk_counter = Counter('enrichment_chunks_indexed_total', ...)
cache_hit_rate = Gauge('enrichment_cache_hit_rate', ...)

@app.get("/metrics")
def prometheus_metrics():
    return Response(generate_latest(), media_type="text/plain")
```

### Real-Time Dashboards
Integrate with Grafana or DataDog for live metrics visualization:
- Ingestion throughput trends
- Cache hit rate over time
- Enrichment latency percentiles
- Background task queue depth

### Metrics Alerts
Add alert thresholds for:
- Enrichment queue overflow (> 5000 pending)
- Cache hit rate drop (< 50%)
- Latency spike (p95 > 5 seconds)
- Enrichment task failures

## FAQ

### Q: How do metrics affect performance?
**A:** Negligible impact. Counter increments are < 1μs. Histograms store samples but don't block ingestion. Total overhead < 1% for typical workloads.

### Q: Can I reset metrics mid-pipeline?
**A:** Yes, use `reset_metrics()` for testing. In production, metrics accumulate for the lifetime of the process. Reset on app restart.

### Q: How are cache hit rates calculated?
**A:** Hit rate = (cache_hits / (cache_hits + cache_misses)) * 100. Displayed as percentage (0-100).

### Q: What if metric collection fails?
**A:** Failures are caught and logged but never block the pipeline. Metrics are best-effort; missing a sample won't affect functionality.

### Q: Can I export metrics to external systems?
**A:** Yes, implement a Prometheus exporter or custom endpoint that calls `get_metrics().get_stats()` and formats for your system.

## Related Documentation

- [Enrichment Pipeline Design](./ENRICHMENT_PIPELINE.md)
- [Testing Patterns](../CLAUDE.md#testing-patterns)
- [Configuration](../CLAUDE.md#configuration--feature-phases)
