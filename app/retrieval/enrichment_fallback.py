"""
On-demand enrichment fallback for non-enriched retrieved chunks (U5).

Provides seamless enrichment during retrieval if chunks haven't been enriched yet:
1. Check retrieved chunks for enrichment status
2. For non-enriched chunks:
   - Check content hash cache (U2)
   - If cache hit: use cached enrichment
   - If cache miss: enrich on-demand, cache result, update Qdrant async
3. Gracefully degrade if enrichment fails (return un-enriched chunk)

Design:
- On-demand enrichment adds ~2-5s to first query for batch of chunks
- Subsequent queries hit cache (no enrichment latency)
- Enrichment is optional; queries succeed even if enrichment fails
- Cache hit rate > 70% after first query
"""

import asyncio
from datetime import datetime, timezone

from app.config.settings import get_settings
from app.enrichment.hash_cache import get_enrichment_cache
from app.models.document import Chunk, RetrievedChunk
from app.models.enrichment import EnrichmentResult, EnrichmentStatus, compute_content_hash
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _get_chunk_enrichment_status(chunk_id: str) -> EnrichmentStatus:
    """
    Get enrichment status for a chunk from Qdrant.

    Args:
        chunk_id: Chunk ID to look up

    Returns:
        EnrichmentStatus (defaults to PENDING if not found)
    """
    try:
        from app.vectorstore.qdrant_client import get_qdrant_client, point_id_for_chunk

        settings = get_settings()
        client = get_qdrant_client()
        point_id = point_id_for_chunk(chunk_id)

        # Retrieve point with payload
        point = client.retrieve(
            collection_name=settings.qdrant_collection,
            ids=[point_id],
            with_payload=True,
        )

        if point and len(point) > 0:
            payload = point[0].payload or {}
            status_str = payload.get("enrichment_status", "PENDING")
            try:
                return EnrichmentStatus(status_str)
            except (ValueError, KeyError):
                return EnrichmentStatus.PENDING
        return EnrichmentStatus.PENDING
    except Exception as exc:
        logger.debug("Failed to get enrichment status for chunk: %s", exc)
        return EnrichmentStatus.PENDING


def _convert_retrieved_to_chunk(
    retrieved: RetrievedChunk, enrichment_status: EnrichmentStatus = EnrichmentStatus.PENDING
) -> Chunk:
    """Convert RetrievedChunk to Chunk for enrichment."""
    return Chunk(
        chunk_id=retrieved.chunk_id,
        document_id=retrieved.document_id,
        filename=retrieved.filename,
        page_number=retrieved.page_number,
        chunk_index=retrieved.chunk_index,
        text=retrieved.text,
        char_start=retrieved.char_start,
        char_end=retrieved.char_end,
        token_count=len(retrieved.text.split()),
        summary="",
        topics=[],
        entities=[],
        embedding_text="",
        enrichment_status=enrichment_status,
        content_hash="",
        enriched_at=None,
        section_id="",
        section_title=retrieved.section_title,
        parent_chunk_id=retrieved.parent_chunk_id,
        parent_text=retrieved.parent_text,
        chunk_role="child",
    )


async def enrich_retrieved_chunks_if_needed(
    chunks: list[RetrievedChunk],
) -> tuple[list[RetrievedChunk], dict[str, int]]:
    """
    Enrich retrieved chunks on-demand if not yet enriched; cache result.

    Checks each chunk's enrichment status from Qdrant:
    1. If COMPLETED: skip (already enriched)
    2. If PENDING/PROCESSING/FAILED: check cache; enrich on-demand if needed

    Returns immediately; updates Qdrant asynchronously.

    Args:
        chunks: Retrieved chunks (may include non-enriched chunks)

    Returns:
        Tuple of:
        - Updated chunks (unchanged; enrichment stored in Qdrant async)
        - Metrics dict: {cache_hits, cache_misses, enriched_chunks}

    Side effects:
    - Updates enrichment cache with new results
    - Queues Qdrant updates for enriched chunks (async, non-blocking)
    """
    settings = get_settings()

    # If enrichment disabled, return as-is
    if not settings.enrichment_enabled:
        return chunks, {"cache_hits": 0, "cache_misses": 0, "enriched_chunks": 0}

    cache = get_enrichment_cache()
    metrics = {"cache_hits": 0, "cache_misses": 0, "enriched_chunks": 0}

    # Phase 1: Check enrichment status and cache for each chunk
    to_enrich = []
    to_enrich_by_hash = {}  # content_hash -> chunk (tracks chunks to be enriched)
    enriched_hashes = {}  # content_hash -> EnrichmentResult (for dedup within batch)

    for retrieved in chunks:
        status = _get_chunk_enrichment_status(retrieved.chunk_id)

        if status == EnrichmentStatus.COMPLETED:
            # Already enriched, skip
            metrics["cache_hits"] += 1
            continue

        # Needs enrichment - convert to Chunk for processing
        temp_chunk = _convert_retrieved_to_chunk(retrieved, enrichment_status=status)
        temp_chunk.content_hash = compute_content_hash(temp_chunk.text)

        # Check for duplicate in current batch (already processing same hash)
        if temp_chunk.content_hash in to_enrich_by_hash:
            # Already queued for enrichment, will get deduped
            metrics["cache_hits"] += 1
            logger.debug(
                "Cache hit (batch dedup) for hash=%s", temp_chunk.content_hash[:8]
            )
            continue

        # Check for duplicate in enriched_hashes (already enriched in this batch)
        if temp_chunk.content_hash in enriched_hashes:
            # Already enriched in this batch, reuse result
            metrics["cache_hits"] += 1
            logger.debug(
                "Cache hit (batch enriched) for hash=%s", temp_chunk.content_hash[:8]
            )
            continue

        # Check global cache
        cached = cache.get(temp_chunk.content_hash)
        if cached:
            enriched_hashes[temp_chunk.content_hash] = cached
            metrics["cache_hits"] += 1
            logger.debug(
                "Cache hit (global) for hash=%s", temp_chunk.content_hash[:8]
            )
        else:
            to_enrich.append(temp_chunk)
            to_enrich_by_hash[temp_chunk.content_hash] = temp_chunk
            metrics["cache_misses"] += 1
            logger.debug(
                "Cache miss for hash=%s, will enrich", temp_chunk.content_hash[:8]
            )

    # Phase 2: Enrich cache misses on-demand (async)
    if to_enrich:
        logger.info(
            "On-demand enrichment for %d chunks (cache misses: %d)",
            len(to_enrich),
            len(to_enrich),
        )

        # Batch enrich chunks
        try:
            # Use existing enrichment logic (sync call)
            # In a real async context, this should use async LLM calls
            # For now, run in thread pool to avoid blocking
            await asyncio.to_thread(_enrich_chunks_batch, to_enrich)

            # Cache the results
            for chunk in to_enrich:
                if chunk.summary or chunk.topics:  # Successful enrichment
                    result = EnrichmentResult(
                        content_hash=chunk.content_hash,
                        summary=chunk.summary,
                        topics=chunk.topics,
                        entities=chunk.entities,
                        enriched_at=datetime.now(timezone.utc).isoformat(),
                    )
                    cache.set(chunk.content_hash, result)
                    enriched_hashes[chunk.content_hash] = result
                    metrics["enriched_chunks"] += 1

            # Queue Qdrant updates (async, non-blocking)
            _queue_qdrant_updates(to_enrich)

        except Exception as exc:
            logger.warning(
                "On-demand enrichment failed; returning un-enriched chunks: %s", exc
            )

    logger.info(
        "Enrichment fallback complete: cache_hits=%d, cache_misses=%d, enriched=%d",
        metrics["cache_hits"],
        metrics["cache_misses"],
        metrics["enriched_chunks"],
    )

    return chunks, metrics


def _enrich_chunks_batch(chunks: list[Chunk]) -> None:
    """
    Enrich a batch of chunks using LLM.

    Uses existing enrichment logic from chunk_enricher.
    Runs synchronously (intended to be called in thread pool for async contexts).

    Args:
        chunks: List of Chunk objects to enrich
    """
    if not chunks:
        return

    # Import here to avoid circular dependencies
    from app.enrichment.chunk_enricher import _enrich_batch

    # Group by filename for context
    by_filename = {}
    for chunk in chunks:
        if chunk.filename not in by_filename:
            by_filename[chunk.filename] = []
        by_filename[chunk.filename].append(chunk)

    # Enrich each file's chunks
    for filename, file_chunks in by_filename.items():
        try:
            _enrich_batch(file_chunks, filename)
            logger.info("Enriched %d chunks for %s", len(file_chunks), filename)
        except Exception as exc:
            logger.warning("Enrichment failed for %s: %s", filename, exc)
            # Set embedding text fallback
            for chunk in file_chunks:
                if not chunk.embedding_text:
                    chunk.embedding_text = chunk.text_for_embedding()


def _queue_qdrant_updates(chunks: list[Chunk]) -> None:
    """
    Queue asynchronous Qdrant updates for enriched chunks.

    Updates enrichment status and metadata in Qdrant without blocking.
    Implementation: For Phase 1, updates are synchronous (acceptable for background).
    For Phase 2, integrate with Celery task queue.

    Args:
        chunks: Enriched chunks to update in Qdrant
    """
    if not chunks:
        return

    try:
        from app.vectorstore.qdrant_client import get_qdrant_client, point_id_for_chunk
        from qdrant_client.http import models as qmodels

        settings = get_settings()
        client = get_qdrant_client()

        # Prepare payload updates
        for chunk in chunks:
            if not chunk.summary and not chunk.topics:
                # Skip chunks that weren't successfully enriched
                continue

            point_id = point_id_for_chunk(chunk.chunk_id)
            payload_update = {
                "summary": chunk.summary,
                "topics": chunk.topics,
                "entities": chunk.entities,
                "enrichment_status": EnrichmentStatus.COMPLETED.value,
                "enriched_at": datetime.now(timezone.utc).isoformat(),
            }

            # Update point payload
            client.update_points(
                collection_name=settings.qdrant_collection,
                points=[
                    qmodels.PointStruct(
                        id=point_id,
                        payload=payload_update,
                    )
                ],
            )

        logger.info("Queued Qdrant updates for %d chunks", len(chunks))

    except Exception as exc:
        logger.warning("Failed to queue Qdrant updates: %s", exc)
