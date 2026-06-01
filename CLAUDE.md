# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start

### Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — set OPENAI_API_KEY for indexing/search
docker compose up -d  # Start Qdrant vector DB
```

### Run API
```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Run Gradio UI (separate terminal)
```bash
python -m gradio_ui.app
# Opens http://127.0.0.1:7860
```

### Tests
```bash
pytest -v                          # Run all tests
pytest tests/test_ask.py -v        # Single test file
pytest tests/test_ask.py::test_ask_response -v  # Single test
```

## Architecture

The pipeline implements a production-grade Research RAG with five major phases:

```
Phase 1: Ingestion
  PDF → extract (+ OCR fallback) → JSON storage

Phase 1B: Indexing & Embeddings
  chunks → embed (OpenAI) → Qdrant + BM25 (keyword index)

Phase 2: Retrieval
  query → hybrid search (dense + BM25, RRF-combined) → Cohere rerank
  → expand parent context → generate answer → citations

Phase 3A: Coverage/Multi-Query
  query classification (fact vs coverage) → plan multiple search queries
  → per-query hybrid retrieval + rerank → merge results

Phase 3B: Enrichment
  Per-chunk LLM metadata: summary, topics, entities
  Used by search to improve retrieval recall

Phase 3C: Parent Expansion  
  Child chunks expand to full parent section context

Phase 3D: Verification
  Coverage verify: second retrieval round if answer looks incomplete
  Answer validation: flags unsupported claims
```

### Key Data Flow

**Ingestion:**
- User uploads PDF → `POST /ingest/index` → PDF extract → chunking → embedding → Qdrant upsert
- Extracted JSON stored in `data/processed/{document_id}.json`
- Chunks include metadata: page number, position, parent section, enrichment fields

**Retrieval:**
- Query → rewriter (optional) → classify query type (fact vs coverage)
- For fact: single search; for coverage: multi-query planner generates 3–8 queries
- Each query: BM25 (on `searchable_text`) + dense (on `embedding_text`) → RRF → Cohere rerank
- Parent expand: child hits expand to parent chunk text (for context)
- Re-rank final list, truncate to `final_k`

**Generation:**
- Retrieved chunks → context builder (with citations) → LLM → answer
- Answer validator checks for unsupported claims
- Coverage verify: if chunks look thin, do supplemental retrieval

## Module Overview

### Core Modules

**`app/ingestion/`** — PDF extraction & storage
- `pdf_extractor.py`: PyMuPDF extraction, text + layout
- `ocr.py`: Tesseract fallback for scanned PDFs
- `ingestor.py`: Coordinates extraction → chunking → storage → indexing
- `storage.py`: Disk I/O (JSON serialization)

**`app/chunking/`** — Token-aware + structure-aware chunking
- `structure_chunker.py`: Parent/child hierarchy; respects section boundaries; uses tiktoken for token counting
- Chunk size/overlap configurable via `CHUNK_SIZE_TOKENS` / `CHUNK_OVERLAP_TOKENS`
- Chunker mode: `structure` (default) respects document structure; alternatives possible

**`app/embeddings/`** — Embedding generation
- `openai_embedder.py`: Batch embed via OpenAI; caches calls; respects rate limits
- Uses `text-embedding-3-small` by default; configurable via `EMBEDDING_MODEL`
- Batch size: `EMBEDDING_BATCH_SIZE` (default 64)

**`app/vectorstore/`** — Vector DB & keyword index
- `qdrant_client.py`: Wraps Qdrant SDK; creates/maintains collection; upsert/search
- Uses `research_chunks` collection (name configurable)
- Stores chunks with full metadata (page, position, text, embedding)

**`app/retrieval/`** — Hybrid search & reranking
- `hybrid.py`: BM25 + dense combined via RRF (reciprocal rank fusion)
- `reranker.py`: Cohere rerank for final reordering (configurable via `RERANK_ENABLED`)
- `parent_expand.py`: Expand child chunks to parent context
- `keyword_index.py`: In-memory BM25 index; rebuilt on startup from Qdrant

**`app/rag/`** — Q&A pipeline
- `pipeline.py`: Main flow: query rewrite → retrieval → generation → validation
- `retriever.py`: Query classification, multi-query planning, retrieval orchestration
- `context.py`: Build LLM context from chunks; extract citations
- `answer_validator.py`: Validate claims against retrieved chunks
- `coverage_verifier.py`: Supplemental retrieval for incomplete coverage
- `prompts.py`: LLM prompt templates

**`app/generation/`** — LLM interaction
- `openai_chat.py`: Query rewrite, answer generation via GPT (configurable via `CHAT_MODEL`)
- Temperature, max tokens configurable

**`app/enrichment/`** — Chunk metadata enrichment
- `enricher.py`: LLM-generated chunk summaries, topics, entities
- Batch processing; `ENRICHMENT_ENABLED` toggles feature
- Improves BM25 relevance via enriched `searchable_text`

**`app/eval/`** — Evaluation harness
- Recall metrics: page-level and keyword coverage
- Compare retrieved chunks against expected answers in `data/eval/recall_coverage.json`

**`app/models/`**
- `document.py`: Request/response Pydantic models; `AskRequest`, `AskResponse`, `RetrievedChunk`
- `retrieval.py`: Constants like `COVERAGE_QUERY_TYPES`

**`app/api/routes/`**
- `ingestion.py`: POST `/ingest*`, GET `/search`
- `ask.py`: POST `/ask` (with optional `mode=coverage`)

**`app/config/`**
- `settings.py`: Pydantic BaseSettings; loads from `.env`; ~20 feature flags & tuning parameters

### UI
- **`gradio_ui/app.py`**: Gradio interface; async calls to FastAPI; document upload, search, Q&A

## Configuration & Feature Phases

All settings live in `.env` and are loaded via Pydantic. Key toggles:

| Setting | Default | Purpose |
|---------|---------|---------|
| `ENRICHMENT_ENABLED` | `true` | Per-chunk LLM summary/topics/entities |
| `MULTI_QUERY_ENABLED` | `true` | Generate multiple search queries per question |
| `QUERY_CLASSIFICATION_ENABLED` | `true` | Classify as fact vs coverage |
| `COVERAGE_VERIFY_ENABLED` | `true` | Supplemental retrieval if coverage thin |
| `ANSWER_VALIDATION_ENABLED` | `true` | Validate claims in answer |
| `PARENT_EXPAND_ENABLED` | `true` | Expand child chunks to parent context |
| `RERANK_ENABLED` | `true` | Cohere rerank (requires `COHERE_API_KEY`) |
| `CHUNKER_MODE` | `structure` | Chunking strategy |
| `CHUNK_SIZE_TOKENS` | 512 | Token limit per chunk |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI model |
| `CHAT_MODEL` | `gpt-4o-mini` | LLM for generation |

**Re-indexing required** after enabling enrichment/structure: re-upload PDFs or call `/ingest/index/{doc_id}` so embeddings and BM25 use the new fields.

## Testing Patterns

**Test fixtures** (`tests/conftest.py`):
- Monkeypatch temp directories for data
- Auto-create `RAW_DIR` / `PROCESSED_DIR`
- Disable enrichment/validation for unit tests (via env var)
- Clear settings cache before/after

**Test structure**:
- Use FastAPI `TestClient` from `app.main:create_app()`
- Tests run with local, temporary file storage; Qdrant must be running for integration tests
- Some tests skip if Qdrant unavailable

## Key Patterns & Conventions

### Chunk Model
Chunks are dictionaries with:
- `chunk_id` (UUID)
- `document_id`, `filename`, `page_number`
- `text` (the content)
- `embedding_text`, `searchable_text` (for retrieval)
- `summary`, `topics`, `entities` (enrichment, optional)
- `parent_chunk_id`, `chunk_index` (hierarchy)

### Query Classification
Questions classified as:
- **Fact**: Single answer expected; standard retrieval (20 chunks, rerank to 5)
- **Coverage**: All instances/risks/etc.; high-recall multi-query (40 chunks per query, rerank to 12)
- Heuristics: presence of "all", "every", "identify", "each" → coverage; LLM fallback if uncertain

### Reranking
BM25 + dense scores combined via Reciprocal Rank Fusion (RRF). Final rerank via Cohere (optional).

### Error Handling
- PDF extraction failures: OCR fallback (if enabled)
- Missing Qdrant: logs warning; /ask returns "no indexed chunks" message
- Generation/embedding failures: HTTP 502 from API

## Development Notes

- **Async**: FastAPI routes async; PDF upload is async; Qdrant client is sync (blocking in async context — acceptable for Phase 1)
- **Logging**: Configured via `LOG_LEVEL` env var; `app.utils.logger` provides `get_logger()`
- **Environment**: Uses python-dotenv; .env not in git (see .gitignore)
- **Dependencies**: Phase 1B = OpenAI + Qdrant. Phase 2 = + Cohere. No external LLM fallbacks.
- **Data**: JSONs stored in `data/processed/`; Qdrant persists to Docker volume

## Troubleshooting

**Qdrant connection fails**: Ensure `docker compose up -d` is running on port 6333
**Embeddings fail**: Check `OPENAI_API_KEY` in .env
**Reranking fails**: Check `COHERE_API_KEY` in .env and `RERANK_ENABLED=true`
**Tests fail with "no fixtures found"**: Run from project root; pytest.ini points to `tests/` subdirectory
**Permission denied on `.venv/`**: Delete and recreate: `rm -rf .venv && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
