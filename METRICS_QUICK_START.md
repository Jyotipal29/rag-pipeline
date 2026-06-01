# Enrichment Metrics Quick Start Guide

## What Is It?

Thread-safe metrics collector for the enrichment pipeline. Tracks:
- Document/chunk ingestion
- Enrichment progress
- Cache effectiveness
- Latency percentiles

## Quick Example

```python
from app.metrics.enrichment_metrics import get_metrics
import time

metrics = get_metrics()

# Track ingestion
metrics.start_ingestion_timer()
metrics.increment_documents_indexed(1)
metrics.increment_chunks_indexed(42)
metrics.stop_ingestion_timer(documents_count=1)

# Track enrichment
metrics.set_enrichment_pending(100)
metrics.record_enrichment_latency(1.5)
metrics.increment_enrichment_completed(1)
metrics.increment_cache_hits(5)

# View results
stats = metrics.get_stats()
print(f"Documents: {stats.documents_indexed}")
print(f"Cache hit rate: {stats.cache_hit_rate:.1f}%")
print(f"Enrichment p95: {stats.enrichment_latency_p95_ms:.2f} ms")

# Log formatted report
metrics.log_stats()
```

## Key Methods

### Counters (Keep Running Total)
```python
metrics.increment_documents_indexed(1)      # +1 documents
metrics.increment_chunks_indexed(42)        # +42 chunks
metrics.increment_enrichment_completed(1)   # +1 chunks enriched
metrics.increment_cache_hits(5)             # +5 cache hits
metrics.increment_cache_misses(2)           # +2 cache misses
```

### Gauges (Current State)
```python
metrics.set_enrichment_pending(100)  # 100 chunks in queue
```

### Timers
```python
metrics.start_ingestion_timer()
# ... do work ...
metrics.stop_ingestion_timer(documents_count=5)
```

### Latencies (Record Sample)
```python
metrics.record_enrichment_latency(1.5)              # seconds
metrics.record_on_demand_enrichment_latency(2.0)   # seconds
```

### Reporting
```python
stats = metrics.get_stats()  # Get snapshot
metrics.log_stats()          # Print formatted report
```

## In Your Code

### Ingestion
```python
# app/ingestion/ingestor.py
from app.metrics.enrichment_metrics import get_metrics

def ingest_and_index_pdf_bytes(file_bytes, filename):
    metrics = get_metrics()
    metrics.increment_documents_indexed(1)
    # ... index chunks ...
    metrics.increment_chunks_indexed(len(chunks))
```

### Enrichment (Celery)
```python
# app/tasks/enrichment_tasks.py
from app.metrics.enrichment_metrics import get_metrics

@celery.task
def enrich_document_task(document_id, chunks):
    metrics = get_metrics()
    metrics.set_enrichment_pending(len(chunks))
    
    for chunk in chunks:
        start = time.time()
        enrich_chunk(chunk)
        duration = time.time() - start
        metrics.record_enrichment_latency(duration)
```

### Retrieval
```python
# app/rag/pipeline.py
from app.metrics.enrichment_metrics import get_metrics

async def answer_question(question):
    metrics = get_metrics()
    chunks = retrieve_chunks(question)
    
    start = time.time()
    chunks = await enrich_on_demand(chunks)
    duration = time.time() - start
    metrics.record_on_demand_enrichment_latency(duration)
```

## Testing

```python
from app.metrics.enrichment_metrics import get_metrics, reset_metrics

def test_ingestion():
    reset_metrics()  # Clean slate
    metrics = get_metrics()
    
    metrics.increment_chunks_indexed(100)
    stats = metrics.get_stats()
    
    assert stats.chunks_indexed == 100
```

## Output Example

```
================================================================================
ENRICHMENT PIPELINE METRICS SNAPSHOT
================================================================================
Timestamp: 2026-06-01T12:00:00Z

--- Ingestion ---
  Documents indexed: 100
  Chunks indexed: 2500
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

## FAQ

**Q: Is it thread-safe?**  
A: Yes. Uses RLock for concurrent access.

**Q: Does it slow down the pipeline?**  
A: No. Counter increments < 1μs. Overhead < 1%.

**Q: What if it fails?**  
A: Failures are logged but never block the pipeline.

**Q: Can I reset it?**  
A: Yes, use `reset_metrics()` for testing.

**Q: How do I export to Prometheus?**  
A: Implement a `/metrics` endpoint that calls `get_stats()`. See docs for example.

## See Also

- Full documentation: `docs/METRICS_USAGE.md`
- Unit tests: `tests/test_enrichment_metrics.py`
- Integration tests: `tests/test_ingestion_with_metrics.py`
- Implementation details: `IMPLEMENTATION_U6.md`
