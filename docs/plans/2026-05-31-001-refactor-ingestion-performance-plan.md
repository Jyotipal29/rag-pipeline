---
name: RAG Ingestion Performance Refactor
status: active
created: 2026-05-31
last_updated: 2026-05-31
---

# Refactor RAG Ingestion Pipeline for Sub-2-Minute Ingestion at Scale

## Summary

Eliminate all LLM calls from the critical ingestion path by moving enrichment (summaries, topics, entities) to asynchronous background processing. Documents become searchable immediately post-upload in < 2 minutes for 100 PDFs. Background enrichment continues async, with on-demand fallback for non-enriched chunks. System remains fully functional without enrichment; enrichment is an optimization layer only.

---

## Problem Frame

Current ingestion pipeline is blocked on LLM enrichment: 100 PDFs (3000-6000 chunks) → ~750 LLM API calls → 25-60+ minutes. Enrichment (chunk summaries, topics, extraction) is not a hard requirement for search functionality—it's an optimization that improves retrieval quality. The pipeline must separate the critical path (ingest → index → searchable) from the optimization path (enrich → cache → improve).

---

## Requirements

**Hard Requirements:**
- 100 PDFs ingested and searchable in < 2 minutes
- No LLM calls in the critical ingestion path
- Documents searchable immediately after upload
- Enrichment processing asynchronous and non-blocking
- Content hash caching for cross-document dedup
- On-demand enrichment fallback for cache misses
- Retrieval works correctly at all enrichment completion states

**Success Criteria:**
- Ingestion latency: < 1.2s per PDF (120s total for 100 PDFs)
- Documents indexed to Qdrant before enrichment starts
- Background enrichment does not block /ask API
- Cache hit ratio > 70% for repeated chunks across documents
- Retrieval quality degradation < 5% during enrichment ramp

---

## Architectural Decisions (Approved)

### Background Enrichment Queue
Use Celery + Redis. Lightweight, maintainable, industry-standard for Python async jobs. Provides retries, status tracking, dead-letter handling, concurrency controls, and metrics.

### Enrichment Strategies
1. **Primary**: Background enrichment runs post-upload, updating metadata asynchronously
2. **Secondary**: On-demand enrichment if retrieval encounters non-enriched chunks; result cached for subsequent queries

### Content Hash Cache Scope
Hash key: `sha256(normalizedChunkText)` only. Cross-document dedup enabled. Do NOT include document ID, section, page number, or metadata in hash to maximize reuse.

### Parent-Level Enrichment Only
Enrich document, section, subsection levels only. Individual chunks inherit parent metadata. Reduces LLM calls by 3-10x while preserving retrieval benefits.

### Retrieval Independence
Enrichment is optional. Retrieval must work at any enrichment state (0% complete through 100%). Enrichment improves quality; is not required for functionality.

---

## High-Level Technical Design

```
CRITICAL PATH (< 2 minutes for 100 PDFs):

Upload PDF
    ↓
Extract Pages
    ↓
Structure Chunking
    ↓
Embed Vectors (OpenAI)
    ↓
Upsert to Qdrant
    ↓
Index BM25
    ↓
Document Searchable ✓

                PARALLEL (Background):
                Enrich Worker (Celery)
                    ↓
                Enrich Parent Chunks (LLM)
                    ↓
                Hash Cache Update
                    ↓
                Qdrant Metadata Update
                    ↓
                Enrichment Complete

RETRIEVAL PATH (On-Demand Fallback):

Query
    ↓
Hybrid Retrieval (BM25 + Dense)
    ↓
Check Enrichment Status
    ├─ COMPLETED → Use enriched metadata
    └─ PENDING/PROCESSING → On-demand enrich first chunk batch → Cache → Return
    ↓
RRF Fusion
    ↓
Cohere Rerank
    ↓
Answer Generation
```

---

## Implementation Units

### U1. Add Enrichment Status Tracking

**Goal:** Track enrichment progress per document; enable on-demand fallback decisions.

**Requirements:** Support retrieval-time queries for enrichment status.

**Dependencies:** None (prerequisite)

**Files:**
- `app/models/document.py` (add EnrichmentStatus enum, fields to Chunk/Document models)
- `app/models/enrichment.py` (new file: status tracking models)

**Approach:**
Add to Chunk model:
- `enrichment_status: Literal["PENDING", "PROCESSING", "COMPLETED", "FAILED"]` (default "PENDING")
- `content_hash: str` (sha256 of normalized text)
- `enriched_at: datetime | None`

Store in Qdrant payload for efficient status queries during retrieval.

**Patterns to follow:** Existing Chunk model structure; use Pydantic Literal for status enum; follow the existing Field() patterns for defaults.

**Test scenarios:**
- New chunks initialize with `enrichment_status="PENDING"`
- Status updates correctly as enrichment progresses: PENDING → PROCESSING → COMPLETED
- Qdrant queries can filter by enrichment_status
- Content hash is computed consistently (normalized text produces same hash)

**Verification:** Unit tests for status enum, Qdrant payload queries return correct status.

---

### U2. Implement Content Hash Caching Layer

**Goal:** Deduplicate enrichment work across documents using content hash.

**Requirements:** Cache enrichment results by chunk hash; reuse across documents.

**Dependencies:** U1

**Files:**
- `app/enrichment/hash_cache.py` (new file: cache service)
- `app/models/enrichment.py` (cache result schema)

**Approach:**
Create `EnrichmentCache` class:
- Key: `sha256(normalizedChunkText)`
- Value: `{summary, topics, entities, enriched_at}`
- Storage: Redis (via Celery backend) or simple in-memory dict with Qdrant as persistence

Normalize chunk text: lowercase, strip whitespace, remove special characters.

**Technical design (directional):**
```
def compute_content_hash(text: str) -> str:
    normalized = text.lower().strip()
    return hashlib.sha256(normalized.encode()).hexdigest()

class EnrichmentCache:
    def get(self, content_hash: str) -> EnrichmentResult | None
    def set(self, content_hash: str, result: EnrichmentResult) -> None
    def exists(self, content_hash: str) -> bool
```

**Patterns to follow:** Use existing storage patterns (Qdrant for persistent cache, or Redis if available).

**Test scenarios:**
- Hash computation is deterministic (same text → same hash)
- Cache hit when identical chunk text exists
- Cache miss when chunk text is unique
- Cache reuse across different documents with same chunk text
- Cache persists across process restarts

**Verification:** Integration test with multiple documents sharing chunk text; verify cache reuse via metrics.

---

### U3. Add Celery + Redis Integration

**Goal:** Background job queue for enrichment worker.

**Requirements:** Job enqueuing, status tracking, retries, dead-letter handling, metrics.

**Dependencies:** None (parallel to ingestion changes)

**Files:**
- `requirements.txt` (add celery, redis)
- `app/config/celery.py` (new file: Celery app config)
- `app/tasks/__init__.py` (new directory)
- `app/tasks/enrichment_tasks.py` (new file: Celery task definitions)

**Approach:**
1. Add Celery and Redis to requirements
2. Create Celery app with Redis broker
3. Define `enrich_document_task()` that:
   - Receives document_id, list of chunks
   - Checks content hash cache for each chunk
   - Calls LLM for un-cached chunks only
   - Updates Chunk.enrichment_status in Qdrant
   - Tracks metrics (cache hits, enrichment time)
4. Wire task enqueuing into `ingest_and_index_many()`

**Patterns to follow:** Existing async patterns in FastAPI app; use settings for Redis URL; follow environment-driven config.

**Test scenarios:**
- Task enqueues after document indexed
- Task retries on transient failures
- Task updates Chunk.enrichment_status correctly
- Dead-letter handling for persistent failures
- Metrics emitted (cache hits, LLM calls, latency)

**Verification:** Integration test: index document, verify task enqueued and completes successfully; check Qdrant status update.

---

### U4. Refactor Ingestion Pipeline (Critical Path Only)

**Goal:** Remove enrichment from `ingest_and_index_*()` functions; make indexing < 2s per PDF.

**Requirements:** Documents indexed and searchable immediately; no LLM calls in critical path.

**Dependencies:** U1, U3

**Files:**
- `app/ingestion/ingestor.py` (modify `ingest_and_index_pdf_bytes`, `ingest_and_index_many`)
- `app/indexing/pipeline.py` (modify `build_and_index_chunks`)
- `app/enrichment/chunk_enricher.py` (conditionally disable enrichment)

**Approach:**
1. In `ingest_and_index_pdf_bytes()`:
   - Skip enrichment step (set `ENRICHMENT_ENABLED=false` at runtime, or branch on flag)
   - Initialize chunks with `enrichment_status="PENDING"`
   - Compute content_hash for each chunk
   - Index to Qdrant immediately
2. After Qdrant upsert succeeds:
   - Enqueue `enrich_document_task(document_id, chunks)`
   - Return response to client immediately (don't wait for enrichment)

**Technical design (directional):**
```python
def ingest_and_index_pdf_bytes(file_bytes: bytes, filename: str) -> IndexingResult:
    ingestion = ingest_pdf_bytes(file_bytes, filename)
    
    # Build chunks WITHOUT enrichment
    chunks = build_chunks_for_document(...)
    
    # Attach hashes for cache lookup
    for chunk in chunks:
        chunk.content_hash = compute_content_hash(chunk.text)
        chunk.enrichment_status = "PENDING"
    
    # Index to Qdrant (no LLM calls)
    indexed = upsert_chunks(chunks)
    
    # Fire background enrichment (async, non-blocking)
    enrich_document_task.delay(ingestion.document_id, chunks)
    
    return IndexingResult(...)
```

**Patterns to follow:** Use existing Chunk model; follow parallel processing patterns from U1 (parallel processing work).

**Test scenarios:**
- Ingestion completes < 2s without enrichment
- Chunks indexed to Qdrant with `enrichment_status="PENDING"`
- Content hash populated for all chunks
- Enrichment task enqueued after indexing
- Parallel processing: 4 PDFs index in parallel (total < 8s for 4 PDFs)

**Verification:** Benchmark: 100 PDFs ingested in < 120s; zero LLM calls during ingestion (via logging); Qdrant contains all chunks with PENDING status.

---

### U5. Implement On-Demand Enrichment Fallback

**Goal:** Enrich chunks during retrieval if not yet enriched; cache result.

**Requirements:** Seamless enrichment on first query; cached for subsequent queries.

**Dependencies:** U1, U2, U3

**Files:**
- `app/retrieval/enrichment_fallback.py` (new file: on-demand enrichment handler)
- `app/rag/pipeline.py` (modify `answer_question()` to call fallback)

**Approach:**
Before answer generation, check retrieved chunks:
1. For each chunk with `enrichment_status != "COMPLETED"`:
   - Check content hash cache (U2)
   - If cache hit: update chunk with cached enrichment, mark COMPLETED
   - If cache miss: call LLM to enrich, cache result, update Qdrant, mark COMPLETED
2. On-demand enrichment happens in-line (adds ~2-5s to first query for batch of chunks)
3. Subsequent queries use cached results (no enrichment latency)

**Technical design (directional):**
```python
async def enrich_retrieved_chunks_if_needed(chunks: list[Chunk]) -> list[Chunk]:
    to_enrich = [c for c in chunks if c.enrichment_status != "COMPLETED"]
    
    for chunk in to_enrich:
        cached = cache.get(chunk.content_hash)
        if cached:
            chunk.summary = cached.summary
            chunk.topics = cached.topics
            chunk.enrichment_status = "COMPLETED"
        else:
            # Enrich on-demand
            enrichment = await llm_enrich_chunk(chunk)
            chunk.summary = enrichment.summary
            chunk.topics = enrichment.topics
            chunk.enrichment_status = "COMPLETED"
            cache.set(chunk.content_hash, enrichment)
            # Update Qdrant async
            queue_qdrant_update(chunk)
    
    return chunks
```

**Patterns to follow:** Async patterns from existing retrieval code; use existing LLM enrichment logic.

**Test scenarios:**
- First query for non-enriched chunks triggers on-demand enrichment
- On-demand enrichment latency tracked (2-5s per batch)
- Second query for same chunks uses cache (no enrichment)
- Cache hit rate > 70% after first query
- Enrichment failures degrade gracefully (return un-enriched chunk)

**Verification:** Integration test: retrieve non-enriched chunks, verify enrichment on-demand; query again, verify cache hit (no enrichment).

---

### U6. Add Enrichment Status Monitoring

**Goal:** Track enrichment progress, cache hit rates, latency; enable observability.

**Requirements:** Metrics exportable; visible in logs.

**Dependencies:** U1-U5

**Files:**
- `app/metrics/enrichment_metrics.py` (new file: metrics collectors)
- `app/main.py` (wire metrics into lifespan)

**Approach:**
Collect metrics:
- `documents_indexed` (counter)
- `chunks_indexed` (counter)
- `enrichment_pending` (gauge: documents in queue)
- `enrichment_completed` (counter)
- `cache_hits` (counter)
- `cache_misses` (counter)
- `enrichment_latency_seconds` (histogram)
- `on_demand_enrichment_latency_seconds` (histogram)
- `ingestion_throughput_docs_per_sec` (gauge)

Log metrics to stdout; optional: export to Prometheus endpoint.

**Patterns to follow:** Use Python logging; optional Prometheus exporter library if available.

**Test scenarios:**
- Metrics counters increment correctly
- Gauges reflect current state (enrichment_pending decreases as background tasks complete)
- Histograms record latency accurately
- No metric emission failures (gracefully skip if collection fails)

**Verification:** Unit test: verify metric increments; integration test: verify metrics after full ingest cycle.

---

### U7. Benchmark and Report

**Goal:** Validate < 2 minute target; measure cache effectiveness; document results.

**Requirements:** Benchmark 100 PDFs; measure ingestion, enrichment, retrieval latency; produce report.

**Dependencies:** U1-U6

**Files:**
- `scripts/benchmark_ingestion.py` (new file: benchmark script)
- `docs/BENCHMARK_2026_05_31.md` (new file: results report)

**Approach:**
1. Create 100 sample PDFs (or reuse existing test PDFs)
2. Benchmark ingestion:
   - Time from upload to "searchable"
   - Measure zero LLM calls during ingestion
   - Track Qdrant upsert latency
3. Benchmark enrichment:
   - Time to full enrichment of all documents
   - Track background task throughput
   - Measure cache hit ratio
4. Benchmark retrieval:
   - Query latency on non-enriched chunks (with on-demand fallback)
   - Query latency on cached chunks
   - Measure retrieval quality (coverage, relevance)
5. Report:
   - Ingestion latency per PDF
   - Total ingestion time for 100 PDFs
   - Background enrichment throughput
   - Cache hit ratio
   - Query latency degradation during ramp

**Test scenarios:**
- 100 PDFs ingest in < 120s
- 100 PDFs fully enriched in < 1 hour (acceptable for background)
- Cache hit ratio > 70%
- Query latency on cached chunks: < 2s
- Query latency on non-enriched chunks (on-demand): < 5s

**Verification:** Benchmark report demonstrates < 2 minute ingestion target met.

---

## Scope Boundaries

### Deferred to Follow-Up Work

- **Priority-based enrichment queue** (U6 requirements mention priority scoring; deferred to Phase 2. Current implementation: FIFO queue sufficient)
- **Distributed enrichment** (scale to multiple workers; deferred pending single-worker baseline performance)
- **Advanced caching strategies** (TTL-based expiry, cache invalidation on chunk updates; deferred)
- **Enrichment quality metrics** (measure improvement from enrichment; deferred to post-launch observability)
- **UI/UX for enrichment status** (show users enrichment progress; deferred)

### Out of Scope

- Changing the embedding model
- Changing Qdrant or BM25 architecture
- Modifying retrieval quality requirements
- API contract changes (except adding enrichment_status field to internal models)
- Redesigning the chunk hierarchy or parent-child relationships

---

## Key Technical Decisions

**Decision: Text-only hash for cache key**
Cross-document chunk dedup maximizes cache hit rates and amortizes enrichment cost. Trade-off: identical text from different contexts will share enrichment (acceptable; summary/topics are mostly context-agnostic).

**Decision: Parent-level enrichment only**
Reduces LLM calls 3-10x compared to chunk-level enrichment. Trade-off: child chunks inherit context; child-specific enrichment not available. Acceptable given retrieval improvements from parent context.

**Decision: On-demand enrichment with latency spike**
Trades first-query latency for immediate searchability. First query on non-enriched document adds 2-5s; subsequent queries cached. Acceptable UX trade-off vs. delaying searchability until enrichment complete.

**Decision: Celery + Redis over custom queue**
Reduces operational overhead; standard pattern; provides retries, dead-letter, metrics. Trade-off: adds Redis dependency. Acceptable for production-grade system.

---

## Dependencies

- **Celery** (>=5.3.0)
- **Redis** (>=7.0.0)
- Existing: OpenAI API, Qdrant, FastAPI, Pydantic

---

## Open Questions / Deferred

- **Enrichment rate limit** — How many concurrent Celery workers to run? (Deferred to implementation; start with 1-2, scale based on OpenAI rate limits)
- **Redis persistence** — In-memory cache or persistent Redis? (Deferred; in-memory sufficient for Phase 1)
- **Chunk-level enrichment fallback** — If parent enrichment fails, fall back to chunk enrichment? (Deferred; accept un-enriched state for now)

---

## Risks & Mitigation

**Risk: Enrichment task queue overflow**
If enrichment tasks enqueue faster than they complete, queue grows unbounded.
*Mitigation:* Implement queue depth monitoring; add rate limiting on ingest if queue exceeds threshold. Alert on queue health.

**Risk: Cache consistency**
If chunks are updated but hash-based cache not invalidated, stale enrichment returned.
*Mitigation:* For Phase 1, accept that chunks are immutable post-indexing (no updates in flight). If updates needed, include chunk version in hash.

**Risk: Partial enrichment visible to users**
If background enrichment updates Qdrant while query in-flight, inconsistent chunks retrieved.
*Mitigation:* Qdrant updates are atomic per chunk. RRF/reranking will work correctly even with mixed enrichment states.

**Risk: On-demand enrichment fails**
If LLM call fails during on-demand enrichment, query still works (returns un-enriched).
*Mitigation:* Log enrichment failures; return chunk as-is. User gets answer, quality slightly degraded. Acceptable.

---

## Sources & Research

- FastAPI async patterns: existing codebase (app/main.py, app/api/routes/*)
- Celery + Redis setup: standard Python async job queue pattern
- Content hashing: SHA256 for deterministic cross-document dedup
- Qdrant filtering: Qdrant SDK supports status field queries for efficient filtering
- Background enrichment: standard post-upload async pattern (GitHub, Slack, etc.)

