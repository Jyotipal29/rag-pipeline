from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from app.ingestion.ingestor import (
    ingest_and_index_many,
    ingest_and_index_pdf_bytes,
    ingest_pdf_bytes,
    index_document,
)
from app.models.document import (
    BatchIndexingResult,
    IndexingResult,
    IngestionResult,
    SearchHit,
    SearchResult,
)
from app.retrieval.hybrid import search_hybrid

router = APIRouter(tags=["ingestion"])


def _validate_pdf(file: UploadFile) -> str:
    filename = file.filename or ""
    if file.content_type not in (None, "application/pdf") and not filename.lower().endswith(
        ".pdf"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are supported",
        )
    return filename or "uploaded.pdf"


@router.post("/ingest", response_model=IngestionResult)
async def ingest_document(file: UploadFile = File(...)) -> IngestionResult:
    filename = _validate_pdf(file)
    file_bytes = await file.read()
    return ingest_pdf_bytes(file_bytes, filename)


@router.post("/ingest/index", response_model=IndexingResult)
async def ingest_and_index(file: UploadFile = File(...)) -> IndexingResult:
    filename = _validate_pdf(file)
    file_bytes = await file.read()
    return ingest_and_index_pdf_bytes(file_bytes, filename)


@router.post("/ingest/index/batch", response_model=BatchIndexingResult)
async def ingest_and_index_batch(
    files: list[UploadFile] = File(...),
) -> BatchIndexingResult:
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one PDF file is required",
        )
    file_items: list[tuple[bytes, str]] = []
    for upload in files:
        filename = _validate_pdf(upload)
        file_items.append((await upload.read(), filename))
    return ingest_and_index_many(file_items)


@router.post("/ingest/{document_id}/index", response_model=IndexingResult)
def index_existing_document(document_id: str) -> IndexingResult:
    try:
        return index_document(document_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/search", response_model=SearchResult)
def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=50),
    document_id: list[str] = Query(default=[]),
) -> SearchResult:
    doc_filter = document_id or None
    try:
        retrieved = search_hybrid(q, limit=limit, document_ids=doc_filter)
        hits = [
            SearchHit(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                filename=chunk.filename,
                page_number=chunk.page_number,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                score=chunk.score,
            )
            for chunk in retrieved
        ]
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Search failed: {exc}",
        ) from exc

    return SearchResult(query=q, hits=hits)
