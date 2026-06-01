import time

from app.chunking.structure_chunker import build_chunks_for_document
from app.config.settings import get_settings
from app.models.document import Chunk, IngestionResult
from app.models.enrichment import EnrichmentStatus, compute_content_hash
from app.retrieval.parent_store import register_parents
from app.utils.logger import get_logger
from app.vectorstore.qdrant_client import upsert_chunks

logger = get_logger(__name__)


def _attach_parent_text(chunks: list[Chunk]) -> list[Chunk]:
    settings = get_settings()
    parents = {c.chunk_id: c.text for c in chunks if c.chunk_role == "parent"}
    updated: list[Chunk] = []
    for chunk in chunks:
        if chunk.chunk_role == "child" and chunk.parent_chunk_id:
            parent_body = parents.get(chunk.parent_chunk_id, "")
            updated.append(
                chunk.model_copy(
                    update={"parent_text": parent_body[: settings.parent_max_chars]}
                )
            )
        else:
            updated.append(chunk)
    return updated


def _prepare_chunks_for_indexing(chunks: list[Chunk]) -> list[Chunk]:
    """
    Prepare chunks for indexing without enrichment (critical path).

    U4: Enrichment moved to background task (enrich_document_task).
    This function:
    1. Sets enrichment_status to PENDING
    2. Computes content_hash for each chunk (U2)
    3. Sets embedding_text for non-enriched chunks
    4. Marks chunks ready for immediate indexing

    Args:
        chunks: List of chunks from build_chunks_for_document

    Returns:
        Updated chunks with PENDING status and content hashes
    """
    for chunk in chunks:
        if chunk.chunk_role == "child":
            # Initialize enrichment status and hash for background enrichment
            chunk.enrichment_status = EnrichmentStatus.PENDING
            chunk.content_hash = compute_content_hash(chunk.text)

            # Set embedding_text for immediate indexing (no LLM required)
            if not chunk.embedding_text:
                chunk.embedding_text = chunk.text_for_embedding()

    return chunks


def build_and_index_chunks(ingestion: IngestionResult) -> tuple[list[Chunk], int]:
    """
    U4: Build and index chunks without enrichment in critical path.

    Flow:
    1. Build chunks from pages (fast, no LLM)
    2. Prepare chunks: add status=PENDING, content_hash (fast, no LLM)
    3. Attach parent text for context
    4. Upsert to Qdrant (fast I/O)
    5. Enqueue background enrichment task (fire-and-forget)

    No LLM calls in this function.
    Enrichment (summaries, topics, entities) happens asynchronously post-indexing.

    Args:
        ingestion: IngestionResult with pages to chunk and index

    Returns:
        Tuple of (chunks, indexed_count)
    """
    start = time.time()

    t0 = time.time()
    chunks = build_chunks_for_document(
        ingestion.pages,
        ingestion.document_id,
        ingestion.filename,
    )
    logger.info(
        "Chunked %s: %d chunks in %.2fs",
        ingestion.document_id,
        len(chunks),
        time.time() - t0,
    )

    # U4: Prepare chunks without enrichment (fast, no LLM)
    t0 = time.time()
    chunks = _prepare_chunks_for_indexing(chunks)
    logger.info(
        "Prepared chunks for indexing (no enrichment): %s in %.2fs",
        ingestion.document_id,
        time.time() - t0,
    )

    t0 = time.time()
    chunks = _attach_parent_text(chunks)
    register_parents(chunks)
    logger.info(
        "Parent expansion for %s in %.2fs",
        ingestion.document_id,
        time.time() - t0,
    )

    t0 = time.time()
    indexed = upsert_chunks(chunks)
    logger.info(
        "Upserted %s: %d chunks in %.2fs",
        ingestion.document_id,
        indexed,
        time.time() - t0,
    )

    # U4: Enqueue background enrichment task (non-blocking, fire-and-forget)
    t0 = time.time()
    _enqueue_enrichment_task(ingestion.document_id, chunks, ingestion.filename)
    logger.info(
        "Enqueued enrichment task for %s in %.2fs",
        ingestion.document_id,
        time.time() - t0,
    )

    total = time.time() - start
    logger.info(
        "Full indexing for %s complete in %.2fs (no enrichment in critical path)",
        ingestion.document_id,
        total,
    )

    return chunks, indexed


def _enqueue_enrichment_task(document_id: str, chunks: list[Chunk], filename: str) -> None:
    """
    Enqueue background enrichment task after document is indexed.

    U4: Fire-and-forget background enrichment via Celery.
    Does not block ingestion flow. Task runs asynchronously.

    If Celery is not available or task queueing fails, logs warning
    and continues (graceful degradation).

    Args:
        document_id: UUID of indexed document
        chunks: All chunks for this document (used for serialization)
        filename: Document filename for LLM context

    Returns:
        None (fire-and-forget)
    """
    try:
        from app.config.celery import get_celery_app
        from app.tasks import enrich_document_task

        celery_app = get_celery_app()

        # Only enqueue if Celery is configured and not in eager mode for fast path
        if celery_app and celery_app.conf.get("broker_url"):
            # Serialize chunks as dicts for task transmission
            chunks_data = [chunk.model_dump() for chunk in chunks]

            # Enqueue task (non-blocking)
            task = enrich_document_task.delay(document_id, chunks_data, filename)
            logger.info(
                "Enqueued enrichment task for document_id=%s (task_id=%s)",
                document_id,
                task.id,
            )
        else:
            logger.debug(
                "Celery not configured; skipping enrichment task queueing for %s",
                document_id,
            )
    except ImportError:
        logger.debug("Celery not available; enrichment will not run asynchronously")
    except Exception as exc:
        logger.warning(
            "Failed to enqueue enrichment task for %s: %s",
            document_id,
            exc,
        )
