from app.chunking.recursive_chunker import chunk_pages
from app.config.settings import get_settings
from app.ingestion.pdf_extractor import extract_pages_from_pdf
from app.ingestion.storage import (
    compute_document_id,
    load_ingestion_result,
    save_ingestion_result,
    save_raw_pdf,
)
from app.models.document import IndexingResult, IngestionResult
from app.utils.logger import get_logger
from app.vectorstore.qdrant_client import upsert_chunks

logger = get_logger(__name__)


def ingest_pdf_bytes(file_bytes: bytes, filename: str) -> IngestionResult:
    """
    Phase 1A orchestrator: persist raw PDF, extract pages, save JSON.
    Idempotent on document_id (content hash).
    """
    settings = get_settings()
    document_id = compute_document_id(file_bytes)
    raw_path = save_raw_pdf(file_bytes, document_id, settings)

    pages = extract_pages_from_pdf(raw_path, document_id, filename)

    result = IngestionResult(
        document_id=document_id,
        filename=filename,
        page_count=len(pages),
        pages=pages,
        raw_path=str(raw_path),
        processed_path=str(settings.processed_dir / f"{document_id}.json"),
    )
    save_ingestion_result(result, settings)
    return result


def index_document(document_id: str) -> IndexingResult:
    """Phase 1B: chunk + embed + upsert from a previously ingested document."""
    ingestion = load_ingestion_result(document_id)
    if ingestion is None:
        raise FileNotFoundError(f"No processed ingestion found for document_id={document_id}")

    chunks = chunk_pages(ingestion.pages, ingestion.document_id, ingestion.filename)
    indexed_count = upsert_chunks(chunks)

    return IndexingResult(
        document_id=ingestion.document_id,
        filename=ingestion.filename,
        page_count=ingestion.page_count,
        chunk_count=len(chunks),
        indexed_count=indexed_count,
        ingestion=ingestion,
    )


def ingest_and_index_pdf_bytes(file_bytes: bytes, filename: str) -> IndexingResult:
    """Full pipeline: extract -> persist JSON -> chunk -> embed -> Qdrant."""
    ingestion = ingest_pdf_bytes(file_bytes, filename)
    chunks = chunk_pages(ingestion.pages, ingestion.document_id, ingestion.filename)
    indexed_count = upsert_chunks(chunks)

    logger.info(
        "Indexed document %s: %s chunks",
        ingestion.document_id,
        indexed_count,
    )

    return IndexingResult(
        document_id=ingestion.document_id,
        filename=ingestion.filename,
        page_count=ingestion.page_count,
        chunk_count=len(chunks),
        indexed_count=indexed_count,
        ingestion=ingestion,
    )
