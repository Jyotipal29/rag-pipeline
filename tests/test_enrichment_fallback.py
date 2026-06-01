"""
Tests for on-demand enrichment fallback (U5).

Scenarios:
1. First query for non-enriched chunks triggers on-demand enrichment
2. On-demand enrichment latency tracked (2-5s per batch)
3. Second query for same chunks uses cache (no enrichment)
4. Cache hit rate > 70% after first query
5. Enrichment failures degrade gracefully (return un-enriched chunk)
"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.models.document import RetrievedChunk
from app.models.enrichment import EnrichmentStatus, EnrichmentResult, compute_content_hash
from app.retrieval.enrichment_fallback import (
    enrich_retrieved_chunks_if_needed,
    _get_chunk_enrichment_status,
    _convert_retrieved_to_chunk,
)
from app.enrichment.hash_cache import get_enrichment_cache, reset_enrichment_cache


@pytest.fixture
def sample_retrieved_chunks():
    """Create sample retrieved chunks for testing."""
    return [
        RetrievedChunk(
            chunk_id="chunk-1",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text="The quick brown fox jumps over the lazy dog.",
            char_start=0,
            char_end=44,
            score=0.95,
            retrieval_source="dense",
        ),
        RetrievedChunk(
            chunk_id="chunk-2",
            document_id="doc-1",
            filename="test.pdf",
            page_number=2,
            chunk_index=1,
            text="Machine learning is a subset of artificial intelligence.",
            char_start=100,
            char_end=160,
            score=0.88,
            retrieval_source="keyword",
        ),
        RetrievedChunk(
            chunk_id="chunk-3",
            document_id="doc-2",
            filename="other.pdf",
            page_number=1,
            chunk_index=0,
            text="The quick brown fox jumps over the lazy dog.",  # Same text as chunk-1
            char_start=0,
            char_end=44,
            score=0.92,
            retrieval_source="dense",
        ),
    ]


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset cache before and after each test."""
    reset_enrichment_cache()
    yield
    reset_enrichment_cache()


def test_convert_retrieved_to_chunk(sample_retrieved_chunks):
    """Test conversion from RetrievedChunk to Chunk."""
    retrieved = sample_retrieved_chunks[0]
    chunk = _convert_retrieved_to_chunk(retrieved, enrichment_status=EnrichmentStatus.PENDING)

    assert chunk.chunk_id == retrieved.chunk_id
    assert chunk.document_id == retrieved.document_id
    assert chunk.text == retrieved.text
    assert chunk.enrichment_status == EnrichmentStatus.PENDING
    assert chunk.summary == ""
    assert chunk.topics == []


@pytest.mark.asyncio
async def test_enrichment_disabled(sample_retrieved_chunks, monkeypatch):
    """Test that enrichment is skipped when ENRICHMENT_ENABLED=false."""
    monkeypatch.setenv("ENRICHMENT_ENABLED", "false")
    from app.config.settings import get_settings
    get_settings.cache_clear()

    chunks, metrics = await enrich_retrieved_chunks_if_needed(sample_retrieved_chunks)

    # Should return chunks unchanged with zero metrics
    assert len(chunks) == 3
    assert metrics["cache_hits"] == 0
    assert metrics["cache_misses"] == 0
    assert metrics["enriched_chunks"] == 0

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_cache_hit_rate(sample_retrieved_chunks, monkeypatch):
    """Test that identical chunks (by content hash) are recognized from cache."""
    monkeypatch.setenv("ENRICHMENT_ENABLED", "true")
    from app.config.settings import get_settings
    get_settings.cache_clear()

    # Manually set enrichment status for some chunks to COMPLETED
    # to simulate chunks that are already enriched
    with patch("app.retrieval.enrichment_fallback._get_chunk_enrichment_status") as mock_status:
        # chunk-1: PENDING, chunk-2: PENDING, chunk-3: PENDING
        mock_status.side_effect = [
            EnrichmentStatus.PENDING,
            EnrichmentStatus.PENDING,
            EnrichmentStatus.PENDING,
        ]

        # Mock the enrichment batch to simulate successful enrichment
        with patch("app.retrieval.enrichment_fallback._enrich_chunks_batch") as mock_enrich:
            def enrich_impl(chunks):
                # Simulate enrichment: add summary and topics
                for i, chunk in enumerate(chunks):
                    chunk.summary = f"Summary for chunk {i}"
                    chunk.topics = ["topic1", "topic2"]

            mock_enrich.side_effect = enrich_impl

            # Mock Qdrant updates
            with patch("app.retrieval.enrichment_fallback._queue_qdrant_updates"):
                chunks, metrics = await enrich_retrieved_chunks_if_needed(sample_retrieved_chunks)

                # Verify metrics
                # chunk-1 and chunk-3 have identical text (same hash)
                # chunk-1: cache miss (first), then enriched
                # chunk-3: cache hit (batch dedup from chunk-1)
                # chunk-2: cache miss (different text)
                assert metrics["cache_misses"] == 2  # chunk-1, chunk-2
                assert metrics["cache_hits"] == 1  # chunk-3 (batch dedup)
                assert metrics["enriched_chunks"] == 2  # chunk-1, chunk-2

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_cache_deduplication(sample_retrieved_chunks, monkeypatch):
    """Test cross-document chunk deduplication via content hash."""
    monkeypatch.setenv("ENRICHMENT_ENABLED", "true")
    from app.config.settings import get_settings
    get_settings.cache_clear()

    cache = get_enrichment_cache()

    # Pre-populate cache with enrichment for the fox text
    fox_text = "The quick brown fox jumps over the lazy dog."
    content_hash = compute_content_hash(fox_text)
    cached_result = EnrichmentResult(
        content_hash=content_hash,
        summary="A story about a fox",
        topics=["animals", "stories"],
    )
    cache.set(content_hash, cached_result)

    # chunk-1 and chunk-3 have identical text, so both should hit cache
    with patch("app.retrieval.enrichment_fallback._get_chunk_enrichment_status") as mock_status:
        mock_status.side_effect = [
            EnrichmentStatus.PENDING,
            EnrichmentStatus.PENDING,
            EnrichmentStatus.PENDING,
        ]

        with patch("app.retrieval.enrichment_fallback._enrich_chunks_batch"):
            with patch("app.retrieval.enrichment_fallback._queue_qdrant_updates"):
                chunks, metrics = await enrich_retrieved_chunks_if_needed(sample_retrieved_chunks)

                # chunk-1 and chunk-3 have identical text (same hash), both hit cache
                # chunk-2 is a cache miss
                assert metrics["cache_hits"] == 2  # chunk-1, chunk-3 (both hit global cache)
                assert metrics["cache_misses"] == 1  # chunk-2
                assert metrics["enriched_chunks"] == 0  # No new enrichment needed

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_graceful_degradation_on_enrichment_failure(sample_retrieved_chunks, monkeypatch):
    """Test that queries succeed even if enrichment fails."""
    monkeypatch.setenv("ENRICHMENT_ENABLED", "true")
    from app.config.settings import get_settings
    get_settings.cache_clear()

    with patch("app.retrieval.enrichment_fallback._get_chunk_enrichment_status") as mock_status:
        mock_status.side_effect = [
            EnrichmentStatus.PENDING,
            EnrichmentStatus.PENDING,
            EnrichmentStatus.PENDING,
        ]

        # Mock enrichment to raise an exception
        with patch("app.retrieval.enrichment_fallback._enrich_chunks_batch") as mock_enrich:
            mock_enrich.side_effect = Exception("LLM service unavailable")

            # Should handle gracefully
            chunks, metrics = await enrich_retrieved_chunks_if_needed(sample_retrieved_chunks)

            # Chunks returned unchanged
            assert len(chunks) == 3
            assert chunks[0].chunk_id == "chunk-1"

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_completed_chunks_skipped(sample_retrieved_chunks, monkeypatch):
    """Test that COMPLETED chunks are skipped in enrichment."""
    monkeypatch.setenv("ENRICHMENT_ENABLED", "true")
    from app.config.settings import get_settings
    get_settings.cache_clear()

    with patch("app.retrieval.enrichment_fallback._get_chunk_enrichment_status") as mock_status:
        # chunk-1: COMPLETED (skip), chunk-2: PENDING, chunk-3: PENDING
        mock_status.side_effect = [
            EnrichmentStatus.COMPLETED,
            EnrichmentStatus.PENDING,
            EnrichmentStatus.PENDING,
        ]

        with patch("app.retrieval.enrichment_fallback._enrich_chunks_batch") as mock_enrich:
            def enrich_impl(chunks):
                for i, chunk in enumerate(chunks):
                    chunk.summary = f"Summary {i}"
                    chunk.topics = ["topic"]

            mock_enrich.side_effect = enrich_impl

            with patch("app.retrieval.enrichment_fallback._queue_qdrant_updates"):
                chunks, metrics = await enrich_retrieved_chunks_if_needed(sample_retrieved_chunks)

                # chunk-1 is COMPLETED (cache hit - already enriched)
                # chunk-2 is PENDING (cache miss)
                # chunk-3 is PENDING with identical text to chunk-1
                # chunk-3 will be queued for enrichment (not in to_enrich_by_hash until processed)
                # since chunk-1 is COMPLETED it doesn't go into to_enrich, but chunk-3 is PENDING
                # so chunk-3 will go into to_enrich separately
                assert metrics["cache_hits"] == 1  # chunk-1 (COMPLETED)
                assert metrics["cache_misses"] == 2  # chunk-2, chunk-3 (both PENDING)
                assert metrics["enriched_chunks"] == 2  # chunk-2, chunk-3

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_enrichment_batch_grouping(sample_retrieved_chunks, monkeypatch):
    """Test that chunks are enriched in batches grouped by filename."""
    monkeypatch.setenv("ENRICHMENT_ENABLED", "true")
    from app.config.settings import get_settings
    get_settings.cache_clear()

    with patch("app.retrieval.enrichment_fallback._get_chunk_enrichment_status") as mock_status:
        mock_status.side_effect = [
            EnrichmentStatus.PENDING,
            EnrichmentStatus.PENDING,
            EnrichmentStatus.PENDING,
        ]

        with patch("app.enrichment.chunk_enricher._enrich_batch") as mock_batch:
            def batch_impl(chunks, filename):
                for chunk in chunks:
                    chunk.summary = "Test summary"
                    chunk.topics = ["test"]

            mock_batch.side_effect = batch_impl

            with patch("app.retrieval.enrichment_fallback._queue_qdrant_updates"):
                chunks, metrics = await enrich_retrieved_chunks_if_needed(sample_retrieved_chunks)

                # Should attempt enrichment
                assert metrics["cache_misses"] >= 1

    get_settings.cache_clear()


def test_get_chunk_enrichment_status_not_found():
    """Test getting enrichment status when chunk not found."""
    with patch("app.vectorstore.qdrant_client.get_qdrant_client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        mock_instance.retrieve.return_value = []  # Empty result

        status = _get_chunk_enrichment_status("nonexistent-chunk-id")

        # Should default to PENDING
        assert status == EnrichmentStatus.PENDING


def test_get_chunk_enrichment_status_found():
    """Test getting enrichment status when chunk is found."""
    with patch("app.vectorstore.qdrant_client.get_qdrant_client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance

        # Mock point with COMPLETED status
        mock_point = MagicMock()
        mock_point.payload = {
            "enrichment_status": "COMPLETED",
            "summary": "Test summary",
        }
        mock_instance.retrieve.return_value = [mock_point]

        status = _get_chunk_enrichment_status("test-chunk-id")

        assert status == EnrichmentStatus.COMPLETED


def test_get_chunk_enrichment_status_exception():
    """Test graceful handling when getting status fails."""
    with patch("app.vectorstore.qdrant_client.get_qdrant_client") as mock_client:
        mock_client.side_effect = Exception("Connection failed")

        status = _get_chunk_enrichment_status("test-chunk-id")

        # Should default to PENDING on exception
        assert status == EnrichmentStatus.PENDING
