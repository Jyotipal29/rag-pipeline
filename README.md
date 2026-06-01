# Research RAG Pipeline

Production-oriented Research RAG: ingestion, structure-aware chunking, LLM enrichment, hybrid retrieval, coverage-oriented multi-query search, Cohere rerank, and grounded Q&A with citations. Gradio UI runs separately from FastAPI.

## Architecture

```
PDF → extract (+ OCR fallback) → structure chunks (parent + child)
    → LLM enrichment (summary/topics) → contextual embeddings → Qdrant + BM25
/ask → classify query → plan concepts/queries → multi-query hybrid → rerank
    → parent context expand → generate → coverage verify → answer validate
```

## Setup

```bash
cd rag-pipeline
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — set OPENAI_API_KEY for indexing/search
```

### Start Qdrant (Phase 1B)

```bash
docker compose up -d
```

## Run

**Terminal 1 — API:**

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Terminal 2 — Gradio UI:**

```bash
source .venv/bin/activate
python -m gradio_ui.app
```

Open http://127.0.0.1:7860

## API

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `POST /ingest` | Extract PDF → JSON (`data/processed/{document_id}.json`) |
| `POST /ingest/index` | Extract + chunk + embed + Qdrant upsert (single PDF) |
| `POST /ingest/index/batch` | Same as above for multiple PDFs in one request |
| `POST /ingest/{document_id}/index` | Index a previously ingested document |
| `GET /search?q=...&limit=5` | Hybrid retrieval (inspect chunks, no LLM) |
| `POST /ask` | Grounded answer with citations (`question`, optional `history`, optional `document_ids`) |
| `POST /ask?mode=coverage` | Force high-recall multi-query retrieval profile |

### Recall / coverage (Phase 3A–3D)

For questions like *"identify every risk"* or *"all company authority clauses"*:

1. **Query classification** — fact vs coverage (heuristics + LLM)
2. **Retrieval planner** — concepts + multiple search queries
3. **Multi-query hybrid** — BM25 (enriched `searchable_text`) + dense (`embedding_text`) → RRF → Cohere rerank
4. **Structure** — page-level parent chunks; child hits expand to parent section text
5. **Enrichment** — per-chunk summary/topics/entities for better recall
6. **Coverage verify** — optional second retrieval round if excerpts look incomplete
7. **Answer validation** — flags unsupported claims

Use `POST /ask?mode=coverage` to force the coverage profile.

Response fields: `query_type`, `retrieval_queries`, `concepts`, `coverage_complete`, `validation_warnings`.

**Re-index required** after enabling enrichment/structure: re-upload PDFs or call `/ingest/index` so embeddings and BM25 use the new fields.

### Eval harness

Edit `data/eval/recall_coverage.json` with expected pages/keywords for your PDFs, then:

```bash
python scripts/run_eval.py
```

## Test

```bash
pytest -v
```

## Project layout

```
app/
  api/routes/ingestion.py
  config/settings.py
  ingestion/          # PDF extract, OCR, storage
  chunking/           # Recursive + structure (parent/child)
  enrichment/         # LLM chunk metadata
  indexing/           # build + index pipeline
  retrieval/          # hybrid, multi-query, parent expand
  rag/                # classify, plan, ask pipeline
  eval/               # recall metrics
  vectorstore/        # Qdrant client
  models/document.py
gradio_ui/app.py
data/raw/             # Original PDFs by document_id
data/processed/       # Extraction JSON by document_id
```
