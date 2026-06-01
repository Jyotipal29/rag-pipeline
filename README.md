# Research RAG Pipeline — Phase 1

Production-oriented Research RAG with modular ingestion, token-aware chunking, OpenAI embeddings, and Qdrant vector search. Gradio UI runs separately from FastAPI.

## Architecture

```
PDF upload (Gradio) → FastAPI /ingest → PyMuPDF extract → JSON on disk
                                    → chunk → embed → Qdrant (optional index=true)
FastAPI /search → embed query → Qdrant → ranked chunks (no LLM yet)
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
| `POST /ingest/index` | Extract + chunk + embed + Qdrant upsert |
| `POST /ingest/{document_id}/index` | Index a previously ingested document |
| `GET /search?q=...&limit=5` | Dense retrieval (inspect chunks before generation) |

## Test

```bash
pytest -v
```

## Project layout

```
app/
  api/routes/ingestion.py
  config/settings.py
  ingestion/          # PDF extract, storage, orchestrator
  chunking/           # Token-aware recursive chunker
  embeddings/         # OpenAI embedder
  vectorstore/        # Qdrant client
  models/document.py
gradio_ui/app.py
data/raw/             # Original PDFs by document_id
data/processed/       # Extraction JSON by document_id
```
