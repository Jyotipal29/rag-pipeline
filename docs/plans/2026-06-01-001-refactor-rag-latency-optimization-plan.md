---
status: active
created: 2026-06-01
---

# Refactor RAG Latency for Sub-15s Response Times

## Summary

Refactor the retrieval pipeline to eliminate latency bottlenecks by removing mandatory enrichment blocking, multi-pass reflection, and fixed 8-query expansion. Replace with adaptive query planning based on query complexity, confidence-based gating for expensive operations (reflection, secondary retrieval), and async-only enrichment. Target: 5–7x faster responses for coverage queries (60s → 8–12s) while preserving answer quality.

---

## Problem Frame

**Current latency bottleneck:**

Coverage queries (e.g., "Create complete inventory of every clause…") execute a 60+ second pipeline:
- Fixed 8-query expansion regardless of question complexity
- 8 embedding calls + vector searches
- Mandatory reflection/critique pass (answer → reranking second retrieval → re-answer)
- Synchronous on-demand enrichment blocking retrieval
- Second retrieval cycle always triggered
- Multiple LLM answer-generation passes

**Target latency:**
- SIMPLE queries: <8s
- COVERAGE queries: 8–12s
- ANALYTICAL queries: 10–15s
- RESEARCH queries: 20–30s

**Success criterion:** 5–7x faster coverage queries with maintained answer quality.

---

## Architecture Simplification

**Current flow:**
```
Query → Classification → Multi-Query Planning (8 queries) → Embedding (8 calls)
→ Vector Search (8 cycles) → Rerank → Enrichment (blocks) → LLM Answer
→ Reflection (always) → Second Retrieval (always) → Re-answer → Response
```

**Target flow:**
```
Query → Strategy Router → Adaptive Query Expansion (1–8 based on strategy)
→ Single Retrieval Cycle → Rerank → LLM Answer → (async enrichment post-response)
```

**Elimination rules:**
- ❌ Automatic second retrieval for all queries
- ❌ Mandatory reflection loop
- ❌ Enrichment in retrieval hot path
- ❌ Fixed 8-query expansion

---

## Key Technical Decisions

### 1. Confidence Scoring

Use simple deterministic heuristics only (no ML models, no LLM judges).

**Formula:**
```
confidence =
  0.4 * retrieval_score +
  0.3 * rerank_score +
  0.2 * source_diversity +
  0.1 * answer_coverage_estimate
```

**Thresholds:**
- ≥ 0.75 → high confidence (skip reflection, skip second retrieval)
- 0.5–0.75 → medium (optional single reflection pass)
- < 0.5 → low (allow second retrieval + reflection)

### 2. Enrichment Policy

Enrichment MUST NOT block user response. Three rules:
- **FAST mode:** NO enrichment
- **BALANCED mode:** NO enrichment  
- **RESEARCH mode:** ONLY async fire-and-forget enrichment AFTER response returned

### 3. Query Expansion Strategy

Do NOT modify existing multi-query planner. Instead, add lightweight routing layer:

```
RetrievalRouter → determines num_queries → MultiQueryPlanner (unchanged)
```

**Adaptive counts:**
- SIMPLE: 1–2 queries
- COVERAGE: 2–3 queries
- ANALYTICAL: 4–5 queries
- DEEP_RESEARCH: 6–8 queries

### 4. Retrieval Profiles

**FAST (<8s)**
- 1 retrieval cycle only
- no enrichment
- no reflection
- single LLM call

**BALANCED (<15s)**
- 1 retrieval cycle
- rerank enabled
- optional reflection (only if confidence < 0.75)
- no enrichment blocking

**RESEARCH (20–30s)**
- 1 retrieval cycle
- rerank enabled
- async enrichment (post-response only)
- reflection only if confidence < 0.75
- second retrieval ONLY if confidence < 0.5

---

## Implementation Units

### U1. Create Retrieval Complexity Analyzer

**Goal:** Route queries to appropriate retrieval depth without hardcoding query types.

**Files:**
- `app/rag/strategy_router.py` (new)
- `app/models/retrieval.py` (add RetrievalStrategy enum)

**Approach:**

Create lightweight RetrievalStrategy enum (SIMPLE, COVERAGE, ANALYTICAL, DEEP_RESEARCH) and route_strategy() function. Analyze query using semantic signals (word length, question marks, intent keywords like "list all", "compare", "synthesize") WITHOUT LLM calls. Map to coverage patterns already established in query_classifier, but for strategy selection rather than coverage detection.

**Patterns to follow:**

Reference existing heuristic_classification in `app/rag/query_classifier.py` for pattern-matching approach.

**Test scenarios:**

- Simple fact question ("What is the interest rate?") → routes to SIMPLE
- Coverage question ("List all clauses") → routes to COVERAGE
- Analytical question ("Compare the two approaches") → routes to ANALYTICAL
- Deep research ("Synthesize the key risks") → routes to DEEP_RESEARCH
- Edge case: Short vague questions → routes to SIMPLE
- Edge case: Very long questions → routes to DEEP_RESEARCH

**Verification:**

`pytest tests/test_strategy_router.py` passes with 100% strategy assignment accuracy on test corpus.

---

### U2. Implement Adaptive Query Expansion Router

**Goal:** Replace fixed 8-query expansion with strategy-based adaptive counts (1–8 queries).

**Files:**
- `app/rag/adaptive_query_planner.py` (new, wraps existing planner)
- `app/retrieval/multi_query.py` (modify to accept adaptive query count)
- `app/models/retrieval.py` (extend RetrievalPlan with strategy field)

**Approach:**

Add adaptive_plan_retrieval() function that accepts RetrievalStrategy and limits query generation. If strategy=SIMPLE, call existing plan_retrieval() but truncate to 1–2 queries. If COVERAGE, 2–3 queries. If ANALYTICAL, 4–5 queries. If DEEP_RESEARCH, 6–8 queries.

Keep existing plan_retrieval() unchanged. Add wrapper layer only.

**Dependencies:** U1 (RetrievalStrategy enum)

**Patterns to follow:**

Reference existing plan_retrieval() in `app/rag/retrieval_planner.py` for LLM query generation approach.

**Test scenarios:**

- SIMPLE strategy generates 1–2 queries
- COVERAGE strategy generates 2–3 queries
- ANALYTICAL strategy generates 4–5 queries
- DEEP_RESEARCH strategy generates 6–8 queries
- Deduplication still works (no duplicate queries)
- Original question always included
- LLM generation honors max_queries limit

**Verification:**

`pytest tests/test_adaptive_query_planner.py` validates query counts per strategy. Latency benchmarks show 4–8s reduction per request vs. fixed 8-query expansion.

---

### U3. Implement Confidence Scoring System

**Goal:** Calculate query-response confidence using deterministic heuristics (retrieval score, rerank score, source diversity, coverage estimate).

**Files:**
- `app/rag/confidence_scorer.py` (new)
- `app/models/retrieval.py` (add ConfidenceScore dataclass)

**Approach:**

Create ConfidenceScore class with score: float (0–1). Implement score_retrieval() function that accepts retrieved_chunks, reranked_chunks, and draft_answer. Calculate four components:

1. **retrieval_score:** 0.4 weight. Min of (rerank_scores) normalized to 0–1. Low if many chunks have low scores.
2. **rerank_score:** 0.3 weight. Mean of top-k rerank scores (if reranking enabled), else 1.0.
3. **source_diversity:** 0.2 weight. Count unique documents / total chunks. Low if all chunks from 1–2 documents.
4. **answer_coverage_estimate:** 0.1 weight. Heuristic based on answer length and number of cited chunks.

Result thresholds:
- ≥ 0.75 = high confidence
- 0.5–0.75 = medium confidence
- < 0.5 = low confidence

**Patterns to follow:**

Reference answer_completeness heuristics in pipeline.py for coverage estimation approach.

**Test scenarios:**

- High-confidence scenario: strong rerank scores, multiple documents, lengthy answer → score ≥ 0.75
- Medium-confidence: moderate scores, 2–3 documents → score 0.5–0.75
- Low-confidence: weak scores, single document → score < 0.5
- Edge case: no chunks → score = 0.0
- Edge case: perfect scores → score = 1.0
- Score is consistent (same input → same score)

**Verification:**

`pytest tests/test_confidence_scorer.py` validates formula and thresholds. Manual inspection of 20 real queries shows reasonable confidence alignment with human judgment.

---

### U4. Gate Reflection Pipeline on Confidence

**Goal:** Run reflection only when confidence < 0.75, not for all queries.

**Files:**
- `app/rag/pipeline.py` (modify answer_question function)

**Approach:**

After generating draft answer and before/instead of mandatory coverage_verify + supplemental_retrieval:

```python
confidence = score_retrieval(final_chunks, reranked_chunks, draft_answer)

if confidence < 0.75:
    # existing reflection logic: coverage_verify + supplemental_retrieval
    complete, missing = verify_coverage(question, concepts, final_chunks, answer)
    if not complete and missing and settings.coverage_max_rounds > 0:
        # supplemental retrieval
else:
    # skip reflection
    coverage_complete = True
```

**Dependencies:** U3 (ConfidenceScore)

**Patterns to follow:**

Reference existing coverage_verify() and supplemental_retrieval() in `app/rag/pipeline.py`. Keep logic unchanged; only gate execution.

**Test scenarios:**

- High confidence (≥ 0.75): skip reflection, return answer immediately
- Medium confidence (0.5–0.75): may run reflection if enabled
- Low confidence (< 0.5): run reflection
- Reflection disabled in settings: always skip regardless of confidence
- Coverage_verify still works when triggered

**Verification:**

`pytest tests/test_reflection_gating.py` validates gate behavior. Latency benchmarks show 10–20s reduction by skipping unnecessary reflection passes.

---

### U5. Gate Secondary Retrieval on Confidence

**Goal:** Run second retrieval cycle only when confidence < 0.5, not for all COVERAGE queries.

**Files:**
- `app/rag/pipeline.py` (modify supplemental_retrieval call)

**Approach:**

In supplemental_retrieval block, check confidence BEFORE running second retrieval:

```python
if confidence < 0.5 and missing and settings.coverage_max_rounds > 0:
    extra = supplemental_retrieval(missing, profile, existing_ids)
    # merge and re-rank
else:
    extra = []
```

If confidence >= 0.5, skip the second retrieval entirely.

**Dependencies:** U3, U4 (confidence score must be available)

**Patterns to follow:**

Reference existing supplemental_retrieval() logic. Keep unchanged; only gate it.

**Test scenarios:**

- Low confidence (< 0.5): trigger second retrieval
- Medium/high confidence (≥ 0.5): skip second retrieval even if coverage incomplete
- Second retrieval merging/reranking still works when triggered
- No second retrieval with confidence < 0.5 returns original chunks only

**Verification:**

`pytest tests/test_secondary_retrieval_gating.py` validates gate. Latency benchmarks show 5–15s reduction by eliminating unnecessary second cycles.

---

### U6. Remove Enrichment from Retrieval Hot Path

**Goal:** Eliminate synchronous enrichment blocking in answer_question(). Enrich only async post-response.

**Files:**
- `app/rag/pipeline.py` (remove/comment _enrich_chunks_on_demand call)
- `app/retrieval/enrichment_fallback.py` (modify to async-only, or disable)
- `app/config/settings.py` (add ENRICHMENT_DEFER_POST_RESPONSE flag if needed)

**Approach:**

In pipeline.py answer_question():
1. Remove or comment out the _enrich_chunks_on_demand() call entirely (lines 74–82 currently).
2. Remove the enrichment_used and enrichment_metrics fields from AskResponse if the response is sent before enrichment.
3. If enrichment is needed for RESEARCH profile, dispatch async fire-and-forget job AFTER response is returned to user.

**Dependencies:** U1 (retrieval profile selection; RESEARCH profile triggers async enrichment)

**Patterns to follow:**

Reference existing Celery task enqueuing in `app/indexing/pipeline.py:_enqueue_enrichment_task` for async job pattern.

**Test scenarios:**

- FAST profile: no enrichment triggered
- BALANCED profile: no enrichment triggered
- RESEARCH profile: async enrichment job enqueued post-response (fire-and-forget)
- Answer returned without waiting for enrichment
- Enrichment errors don't block user response
- Cache hits still used when available (no blocking)

**Verification:**

`pytest tests/test_no_enrichment_blocking.py` confirms response time includes zero enrichment latency. RESEARCH queries still get enrichment (asynchronously); FAST/BALANCED never trigger enrichment.

---

### U7. Implement Retrieval Profiles and End-to-End Latency Metrics

**Goal:** Create FAST/BALANCED/RESEARCH profiles that auto-route by strategy. Add detailed timing metrics for observability.

**Files:**
- `app/models/retrieval.py` (add RetrievalProfile updates with profile_name field)
- `app/rag/pipeline.py` (refactor answer_question to use profile-based logic)
- `app/metrics/retrieval_metrics.py` (new; track latency per phase)
- `tests/test_retrieval_profiles.py` (new)

**Approach:**

1. **Profile selection:** In retrieve_for_question or early in answer_question, map RetrievalStrategy → RetrievalProfile name (FAST, BALANCED, RESEARCH).

2. **FAST profile behavior:**
   - Use strategy=SIMPLE
   - 1–2 queries
   - Single retrieval cycle
   - Rerank enabled
   - No enrichment
   - No reflection
   - Single LLM call
   - Target: <8s

3. **BALANCED profile behavior:**
   - Use strategy=COVERAGE or ANALYTICAL
   - 2–5 queries
   - Single retrieval cycle
   - Rerank enabled
   - No enrichment blocking
   - Optional reflection (if confidence < 0.75)
   - Single LLM call
   - Target: <15s

4. **RESEARCH profile behavior:**
   - Use strategy=DEEP_RESEARCH
   - 6–8 queries
   - Single retrieval cycle (not mandatory second)
   - Rerank enabled
   - Async enrichment post-response
   - Reflection only if confidence < 0.75
   - Second retrieval only if confidence < 0.5
   - Target: 20–30s

5. **Metrics:** Instrument pipeline to track:
   - query_id (unique per request)
   - strategy (SIMPLE, COVERAGE, ANALYTICAL, DEEP_RESEARCH)
   - profile_name (FAST, BALANCED, RESEARCH)
   - num_queries (actual queries generated)
   - retrieval_cycles (1 or 2)
   - enrichment_used (boolean)
   - reflection_used (boolean)
   - confidence_score (float)
   - latency_ms (dict with breakdowns: classification_ms, planning_ms, embedding_ms, retrieval_ms, rerank_ms, enrichment_ms, reflection_ms, llm_ms, total_ms)

   Log as structured JSON per request.

**Dependencies:** U1, U2, U3, U4, U5, U6

**Patterns to follow:**

Reference RetrievalProfile in `app/rag/query_classifier.py:profile_for_query_type`. Reference metrics collection pattern in existing code.

**Test scenarios:**

- FAST profile: query routes to SIMPLE, uses 1–2 queries, completes <8s
- BALANCED profile: query routes to COVERAGE/ANALYTICAL, uses 2–5 queries, completes <15s
- RESEARCH profile: query routes to DEEP_RESEARCH, uses 6–8 queries, completes 20–30s
- Coverage question (60+ second current) routes to BALANCED/RESEARCH, completes 8–12s
- Metrics logged for every request with accurate latency breakdown
- Confidence gating works (reflection/secondary retrieval gated per confidence)
- No enrichment blocks FAST/BALANCED responses

**Verification:**

`pytest tests/test_retrieval_profiles.py` validates profile behavior. Latency benchmarks:
- SIMPLE queries: <8s (target met)
- COVERAGE queries: 8–12s (5–7x improvement from 60s baseline)
- ANALYTICAL queries: 10–15s (achieves target)
- RESEARCH queries: 20–30s (achieves target)

Manual inspection of 50 query logs confirms strategy classification, profile routing, and latency breakdown accuracy.

---

## Scope Boundaries

### Deferred to Follow-Up Work

- Real-time monitoring dashboard for latency metrics
- Cost optimization (token usage per profile)
- Query rewriting integration improvements
- Advanced confidence scoring using learned models (future enhancement)

### Non-Goals

- Changing vector store or embedding model
- Redesigning chunking strategy
- Modifying Qdrant schema
- Changing reranking behavior (Cohere stays as-is)
- Caching query results (only enrichment cached)
- Redesigning document models

---

## System-Wide Impact

**Affected systems:**
- Main RAG pipeline (`app/rag/pipeline.py`) — refactored for gating and profiling
- Retrieval layer (`app/retrieval/multi_query.py`) — query expansion now adaptive
- Query classification (`app/rag/query_classifier.py`) — unchanged, but used by new router
- Enrichment system — decoupled from critical path
- API responses — may no longer include enrichment_used/enrichment_metrics fields
- Logging — new detailed latency metrics added

**User-facing impact:**
- Much faster response times (5–7x for coverage queries)
- Responses no longer block on enrichment
- Reduced API latency variability
- Answer quality maintained (same underlying retrieval + generation, just optimized routing)

---

## Risks & Dependencies

**Risk: Answer quality degradation from skipped reflection**
- Mitigation: Confidence scoring gates reflection only when high confidence detected. Low-confidence answers still get reflection.
- Monitor: Compare answer quality metrics before/after across test corpus.

**Risk: Secondary retrieval never triggered if confidence always ≥ 0.5**
- Mitigation: Confidence formula designed to be conservative (low rerank scores → low confidence). Test on weak-retrieval scenarios.
- Monitor: Track how often secondary retrieval triggered; adjust thresholds if needed.

**Risk: Async enrichment jobs not completing**
- Mitigation: Fire-and-forget enrichment doesn't block response; failures are non-critical.
- Monitor: Track enrichment task completion rates; log failures.

**Dependency:** Settings must have ENRICHMENT_ENABLED, COVERAGE_VERIFY_ENABLED, and timing controls present in .env.

---

## Testing Strategy

Each unit has specific test scenarios and verification criteria (see Implementation Units section). At integration level:

- Latency benchmarks on 100-query corpus (mix of SIMPLE, COVERAGE, ANALYTICAL, DEEP_RESEARCH) confirm targets met
- Answer quality metrics (BLEU, exact match on evaluation set) maintained vs. baseline
- Confidence score distribution reasonable (not all high, not all low)
- Logs validate strategy routing and profile selection
- No enrichment blocking confirmed for FAST/BALANCED profiles
- Reflection/secondary retrieval only triggered when confidence < threshold

---

## Observability & Metrics

Structured JSON logging per request:

```json
{
  "query_id": "req-12345",
  "strategy": "coverage",
  "profile": "balanced",
  "num_queries": 3,
  "retrieval_cycles": 1,
  "confidence_score": 0.68,
  "enrichment_used": false,
  "reflection_used": true,
  "second_retrieval_used": false,
  "latency_ms": {
    "classification": 150,
    "planning": 300,
    "embedding": 450,
    "retrieval": 900,
    "rerank": 200,
    "enrichment": 0,
    "reflection": 800,
    "llm": 1200,
    "total": 4000
  }
}
```

Log all requests; aggregate metrics per profile/strategy to measure improvement.
