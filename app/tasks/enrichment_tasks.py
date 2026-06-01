"""
Celery task for background enrichment of documents (U3).

Implements `enrich_document_task()` which:
1. Receives document_id and list of chunks to enrich
2. Checks content hash cache (U2) for each chunk
3. Calls LLM for un-cached chunks only
4. Updates Chunk.enrichment_status in Qdrant
5. Tracks metrics (cache hits, enrichment time, LLM calls)

Task runs asynchronously in background after document is indexed and searchable.
Retries automatically on transient failures; moves to dead-letter queue on persistent failures.
"""

from datetime import datetime, timezone
from time import time

from celery import Task

from app.config.celery import get_celery_app
from app.config.settings import get_settings
from app.enrichment.hash_cache import get_enrichment_cache
from app.models.document import Chunk
from app.models.enrichment import EnrichmentStatus, compute_content_hash
from app.vectorstore.qdrant_client import get_qdrant_client
from app.utils.logger import get_logger

logger = get_logger(__name__)

celery_app = get_celery_app()


class EnrichmentTask(Task):
    """Base task class for enrichment with custom error handling."""

    autoretry_for = (Exception,)
    max_retries = 3
    default_retry_delay = 60  # seconds


@celery_app.task(bind=True, base=EnrichmentTask)
def enrich_document_task(
    self, document_id: str, chunks_data: list[dict], filename: str = ""
) -> dict:
    """
    Background task to enrich a document's chunks asynchronously.

    Flow:
    1. Deserialize chunks from dict representation
    2. For each chunk:
       a. Compute content hash if not provided
       b. Check enrichment cache (U2) for hit
       c. If hit: restore cached enrichment metadata
       d. If miss: call LLM to enrich chunk
       e. Cache result and update status
    3. Upsert updated chunks to Qdrant with COMPLETED status
    4. Track metrics: cache hits, LLM calls, latency

    Args:
        document_id: UUID of document being enriched
        chunks_data: List of Chunk objects (as dicts) to enrich
        filename: Document filename (for logging and LLM context)

    Returns:
        Task result dict with:
        - document_id: Document UUID
        - total_chunks: Total chunks processed
        - enriched_chunks: Chunks with enrichment completed
        - cache_hits: Count of cache hits
        - cache_misses: Count of cache misses
        - failed_chunks: Chunks that failed enrichment
        - total_latency_seconds: Total task duration
        - llm_calls: Count of LLM API calls made

    Raises:
        ValueError: If document_id or chunks invalid
        Exception: Transient failures trigger automatic retries (3x with 60s backoff)
    """
    settings = get_settings()
    cache = get_enrichment_cache()
    qdrant_client = get_qdrant_client()

    task_start = time()
    logger.info(
        "Starting enrichment task for document_id=%s, chunk_count=%d",
        document_id,
        len(chunks_data),
    )

    if not document_id or not chunks_data:
        raise ValueError(f"Invalid task parameters: document_id={document_id}, chunks={len(chunks_data)}")

    # Deserialize chunks from dict representation
    try:
        chunks = [Chunk(**chunk_dict) for chunk_dict in chunks_data]
    except Exception as exc:
        logger.error("Failed to deserialize chunks: %s", exc)
        raise

    # Counters for metrics
    cache_hits = 0
    cache_misses = 0
    failed_chunks = 0
    enriched_chunks = 0
    llm_calls = 0

    # Process chunks: check cache, enrich if needed, update status
    chunks_to_enrich = []
    for chunk in chunks:
        try:
            # Compute content hash if not already set
            if not chunk.content_hash:
                chunk.content_hash = compute_content_hash(chunk.text)

            # Check cache
            cached = cache.get(chunk.content_hash)
            if cached:
                # Cache hit: restore enrichment metadata
                chunk.summary = cached.summary
                chunk.topics = cached.topics
                chunk.entities = cached.entities
                chunk.enrichment_status = EnrichmentStatus.COMPLETED
                chunk.enriched_at = datetime.now(timezone.utc)
                cache_hits += 1
                enriched_chunks += 1
                logger.debug(
                    "Cache hit for chunk_id=%s (hash=%s)",
                    chunk.chunk_id,
                    chunk.content_hash[:8],
                )
            else:
                # Cache miss: mark for LLM enrichment
                cache_misses += 1
                chunk.enrichment_status = EnrichmentStatus.PROCESSING
                chunks_to_enrich.append(chunk)
        except Exception as exc:
            logger.warning("Failed to prepare chunk for enrichment: %s", exc)
            chunk.enrichment_status = EnrichmentStatus.FAILED
            failed_chunks += 1

    # Batch enrich remaining chunks via LLM
    if chunks_to_enrich:
        # Import here to avoid circular dependency
        from app.enrichment.chunk_enricher import _enrich_batch

        batch_size = settings.enrichment_batch_size
        for start_idx in range(0, len(chunks_to_enrich), batch_size):
            batch = chunks_to_enrich[start_idx : start_idx + batch_size]
            try:
                logger.info(
                    "Enriching batch for document_id=%s (batch_size=%d/%d)",
                    document_id,
                    len(batch),
                    len(chunks_to_enrich),
                )
                # Call LLM enrichment
                _enrich_batch(batch, filename or document_id)
                llm_calls += len(batch)

                # Update status and cache for enriched chunks
                for chunk in batch:
                    chunk.enrichment_status = EnrichmentStatus.COMPLETED
                    chunk.enriched_at = datetime.now(timezone.utc)
                    enriched_chunks += 1

                    # Cache enrichment result
                    from app.models.enrichment import EnrichmentResult

                    result = EnrichmentResult(
                        content_hash=chunk.content_hash,
                        summary=chunk.summary,
                        topics=chunk.topics,
                        entities=chunk.entities,
                        enriched_at=chunk.enriched_at.isoformat(),
                    )
                    cache.set(chunk.content_hash, result)
                    logger.debug("Cached enrichment result for hash=%s", chunk.content_hash[:8])

            except Exception as exc:
                logger.error("Batch enrichment failed: %s", exc)
                for chunk in batch:
                    chunk.enrichment_status = EnrichmentStatus.FAILED
                    failed_chunks += 1

    # Upsert all chunks to Qdrant with updated enrichment status
    try:
        logger.info(
            "Upserting %d chunks to Qdrant for document_id=%s",
            len(chunks),
            document_id,
        )
        qdrant_client.upsert_chunks(chunks)
    except Exception as exc:
        logger.error("Failed to upsert chunks to Qdrant: %s", exc)
        # Task will auto-retry; chunks remain in PROCESSING state

    task_latency = time() - task_start

    result = {
        "document_id": document_id,
        "total_chunks": len(chunks),
        "enriched_chunks": enriched_chunks,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "failed_chunks": failed_chunks,
        "total_latency_seconds": task_latency,
        "llm_calls": llm_calls,
    }

    logger.info(
        "Enrichment task completed for document_id=%s: %s",
        document_id,
        result,
    )

    return result


@celery_app.task(bind=True)
def check_enrichment_status(self, document_id: str) -> dict:
    """
    Check enrichment status of a document.

    Queries Qdrant for chunks belonging to document and counts by enrichment_status.

    Args:
        document_id: UUID of document to check

    Returns:
        Status dict with:
        - document_id: Document UUID
        - total_chunks: Total chunks for document
        - pending: Count with PENDING status
        - processing: Count with PROCESSING status
        - completed: Count with COMPLETED status
        - failed: Count with FAILED status
        - completion_percentage: 0-100 completion ratio
    """
    qdrant_client = get_qdrant_client()
    logger.info("Checking enrichment status for document_id=%s", document_id)

    try:
        # Query Qdrant for chunks with this document_id
        query_filter = {
            "must": [
                {
                    "key": "document_id",
                    "match": {"value": document_id},
                }
            ]
        }
        points, _ = qdrant_client.client.scroll(
            collection_name=qdrant_client.collection_name,
            scroll_filter=query_filter,
            limit=10000,
        )

        status_counts = {
            "PENDING": 0,
            "PROCESSING": 0,
            "COMPLETED": 0,
            "FAILED": 0,
        }

        for point in points:
            status = point.payload.get("enrichment_status", "PENDING")
            status_counts[status] = status_counts.get(status, 0) + 1

        total = sum(status_counts.values())
        completion_percentage = (
            round((status_counts["COMPLETED"] / total) * 100, 2) if total > 0 else 0
        )

        result = {
            "document_id": document_id,
            "total_chunks": total,
            "pending": status_counts["PENDING"],
            "processing": status_counts["PROCESSING"],
            "completed": status_counts["COMPLETED"],
            "failed": status_counts["FAILED"],
            "completion_percentage": completion_percentage,
        }

        logger.info("Enrichment status for document_id=%s: %s", document_id, result)
        return result

    except Exception as exc:
        logger.error("Failed to check enrichment status: %s", exc)
        raise
