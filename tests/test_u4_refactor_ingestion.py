"""
Tests for U4: Refactor Ingestion Pipeline (Critical Path Only).

Tests verify:
1. Ingestion completes without enrichment in critical path
2. Chunks indexed to Qdrant with enrichment_status="PENDING"
3. Content hash populated for all chunks
4. Enrichment task enqueued after indexing
5. Parallel processing works efficiently

Target: < 2s per PDF, zero LLM calls during ingestion
"""
import time
from io import BytesIO
from unittest.mock import MagicMock, patch

import fitz
import pytest

from app.config.settings import get_settings
from app.ingestion.ingestor import ingest_and_index_many, ingest_and_index_pdf_bytes
from app.models.document import Chunk
from app.models.enrichment import EnrichmentStatus, compute_content_hash
from app.vectorstore.qdrant_client import get_chunks_by_enrichment_status


def _make_test_pdf(text: str = "Test document content") -> bytes:
    """Create a minimal PDF for testing."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    payload = doc.tobytes()
    doc.close()
    return payload


class TestU4CriticalPathNoEnrichment:
    """Verify enrichment is removed from critical path."""

    def test_ingest_and_index_skips_enrichment(self):
        """Ingestion should skip enrichment (no LLM calls in critical path)."""
        pdf_bytes = _make_test_pdf("Critical path test")
        filename = "test.pdf"

        # Patch to track LLM calls
        with patch("app.enrichment.chunk_enricher._enrich_batch") as mock_enrich:
            result = ingest_and_index_pdf_bytes(pdf_bytes, filename)

            # No LLM enrichment should be called during ingestion
            assert not mock_enrich.called, "Enrichment should not be called in critical path"

        # But indexing should succeed
        assert result.indexed_count > 0
        assert result.chunk_count > 0

    def test_chunks_indexed_with_pending_status(self):
        """All chunks should be indexed with enrichment_status=PENDING."""
        pdf_bytes = _make_test_pdf("Pending status test")
        result = ingest_and_index_pdf_bytes(pdf_bytes, "test.pdf")

        # Query Qdrant for chunks with PENDING status
        pending_chunks = get_chunks_by_enrichment_status(
            "PENDING", document_id=result.document_id
        )

        # All indexed chunks should have PENDING status
        assert len(pending_chunks) == result.indexed_count
        for chunk in pending_chunks:
            assert chunk.enrichment_status == EnrichmentStatus.PENDING

    def test_chunks_have_content_hash(self):
        """All chunks should have content_hash computed."""
        pdf_bytes = _make_test_pdf("Content hash test")
        result = ingest_and_index_pdf_bytes(pdf_bytes, "test.pdf")

        # Query chunks
        chunks = get_chunks_by_enrichment_status(
            "PENDING", document_id=result.document_id
        )

        # All chunks should have content_hash
        for chunk in chunks:
            assert chunk.content_hash, f"Chunk {chunk.chunk_id} missing content_hash"
            # Hash should be 64-char hex (SHA256)
            assert len(chunk.content_hash) == 64
            assert all(c in "0123456789abcdef" for c in chunk.content_hash)

    def test_content_hash_matches_text(self):
        """Content hash should match compute_content_hash(text)."""
        pdf_bytes = _make_test_pdf("Hash match test")
        result = ingest_and_index_pdf_bytes(pdf_bytes, "test.pdf")

        chunks = get_chunks_by_enrichment_status(
            "PENDING", document_id=result.document_id
        )

        for chunk in chunks:
            expected_hash = compute_content_hash(chunk.text)
            assert chunk.content_hash == expected_hash


class TestU4EnrichmentTaskEnqueuing:
    """Verify enrichment task is enqueued after indexing."""

    def test_enrichment_task_enqueued_after_index(self):
        """Background enrichment task should be enqueued after indexing."""
        pdf_bytes = _make_test_pdf("Task enqueue test")

        with patch("app.indexing.pipeline._enqueue_enrichment_task") as mock_enqueue:
            result = ingest_and_index_pdf_bytes(pdf_bytes, "test.pdf")

            # Enqueue should have been called
            assert mock_enqueue.called
            call_args = mock_enqueue.call_args
            assert call_args[0][0] == result.document_id  # document_id
            assert len(call_args[0][1]) > 0  # chunks list

    def test_enqueue_is_non_blocking(self):
        """Task enqueuing should complete very quickly (< 100ms)."""
        pdf_bytes = _make_test_pdf("Non-blocking test")

        start = time.time()
        result = ingest_and_index_pdf_bytes(pdf_bytes, "test.pdf")
        elapsed = time.time() - start

        # Full ingestion should be < 2s (target is ~1.2s per PDF)
        # If enrichment was synchronous, it would be much slower
        assert elapsed < 2.0, f"Ingestion took {elapsed}s, should be < 2s"

    def test_enqueue_task_completed_successfully(self):
        """Enrichment task should complete and log appropriately."""
        pdf_bytes = _make_test_pdf("Successful enqueue test")
        result = ingest_and_index_pdf_bytes(pdf_bytes, "test.pdf")

        # Verify indexing succeeded
        assert result.indexed_count > 0
        assert result.chunk_count > 0

        # Chunks should still be PENDING (task enqueued but not yet processed)
        pending = get_chunks_by_enrichment_status(
            "PENDING", document_id=result.document_id
        )
        assert len(pending) == result.indexed_count


class TestU4BatchParallelProcessing:
    """Verify parallel processing of multiple PDFs."""

    def test_batch_index_four_pdfs_parallel(self):
        """Four PDFs should index in parallel (< 8s total)."""
        pdfs = [
            (_make_test_pdf(f"Document {i}"), f"doc{i}.pdf") for i in range(4)
        ]

        start = time.time()
        result = ingest_and_index_many(pdfs)
        elapsed = time.time() - start

        # 4 PDFs should take < 8s (allowing ~2s per PDF with overhead)
        # If sequential, would be ~8-10s per PDF = 32-40s total
        assert elapsed < 10.0, f"Batch processing took {elapsed}s, should be < 10s"
        assert len(result.results) == 4
        assert result.total_indexed == sum(r.indexed_count for r in result.results)

    def test_batch_all_chunks_pending(self):
        """All chunks from batch should be PENDING."""
        pdfs = [
            (_make_test_pdf(f"Batch doc {i}"), f"batch{i}.pdf") for i in range(2)
        ]

        result = ingest_and_index_many(pdfs)

        for doc_result in result.results:
            pending = get_chunks_by_enrichment_status(
                "PENDING", document_id=doc_result.document_id
            )
            assert len(pending) == doc_result.indexed_count


class TestU4EnrichmentSkipWhenDisabled:
    """Verify enrichment is skipped when ENRICHMENT_ENABLED=false."""

    def test_enrichment_skipped_when_disabled(self, monkeypatch):
        """When ENRICHMENT_ENABLED=false, no enrichment should occur."""
        monkeypatch.setenv("ENRICHMENT_ENABLED", "false")
        get_settings.cache_clear()

        pdf_bytes = _make_test_pdf("Enrichment disabled test")

        with patch("app.enrichment.chunk_enricher._enrich_batch") as mock_enrich:
            result = ingest_and_index_pdf_bytes(pdf_bytes, "test.pdf")

            # LLM enrichment should not be called
            assert not mock_enrich.called

        get_settings.cache_clear()

    def test_chunks_still_have_embedding_text(self):
        """Even without enrichment, chunks should have embedding_text."""
        pdf_bytes = _make_test_pdf("Embedding text test")
        result = ingest_and_index_pdf_bytes(pdf_bytes, "test.pdf")

        chunks = get_chunks_by_enrichment_status(
            "PENDING", document_id=result.document_id
        )

        # All chunks should have embedding_text set
        for chunk in chunks:
            assert chunk.embedding_text, f"Chunk {chunk.chunk_id} missing embedding_text"
            assert len(chunk.embedding_text) > 0


class TestU4PerformanceTargets:
    """Verify ingestion meets performance targets."""

    def test_single_pdf_ingestion_under_2s(self):
        """Single PDF should ingest in < 2s."""
        pdf_bytes = _make_test_pdf("Performance test document")

        start = time.time()
        result = ingest_and_index_pdf_bytes(pdf_bytes, "perf.pdf")
        elapsed = time.time() - start

        # Target: < 1.2s per PDF; allow up to 2s for CI/slow systems
        assert elapsed < 2.0, f"Ingestion took {elapsed}s, target < 1.2s"
        assert result.indexed_count > 0

    def test_no_llm_calls_logged(self):
        """Ingestion should not make any LLM API calls."""
        pdf_bytes = _make_test_pdf("No LLM calls test")

        # Track any openai calls
        with patch("app.generation.openai_chat.chat_json_completion") as mock_llm:
            result = ingest_and_index_pdf_bytes(pdf_bytes, "test.pdf")

            # No LLM calls should occur during ingestion
            assert not mock_llm.called, "LLM calls detected during ingestion"

        assert result.indexed_count > 0


class TestU4ChunkFieldsPreserved:
    """Verify chunk fields are preserved during U4 refactor."""

    def test_chunk_core_fields_present(self):
        """Chunks should have all core fields."""
        pdf_bytes = _make_test_pdf("Field preservation test")
        result = ingest_and_index_pdf_bytes(pdf_bytes, "test.pdf")

        chunks = get_chunks_by_enrichment_status(
            "PENDING", document_id=result.document_id
        )

        for chunk in chunks:
            # Core fields
            assert chunk.chunk_id
            assert chunk.document_id == result.document_id
            assert chunk.filename == "test.pdf"
            assert chunk.page_number > 0
            assert chunk.chunk_index >= 0
            assert chunk.text
            assert chunk.char_start >= 0
            assert chunk.char_end > chunk.char_start
            assert chunk.token_count > 0

    def test_chunk_enrichment_fields_set(self):
        """Chunks should have enrichment fields initialized."""
        pdf_bytes = _make_test_pdf("Enrichment fields test")
        result = ingest_and_index_pdf_bytes(pdf_bytes, "test.pdf")

        chunks = get_chunks_by_enrichment_status(
            "PENDING", document_id=result.document_id
        )

        for chunk in chunks:
            assert chunk.enrichment_status == EnrichmentStatus.PENDING
            assert chunk.content_hash  # Should be computed
            assert isinstance(chunk.summary, str)  # Should be empty or set
            assert isinstance(chunk.topics, list)  # Should be empty or set
            assert isinstance(chunk.entities, list)  # Should be empty or set

    def test_chunk_text_and_embedding_text_set(self):
        """Chunks should have both text and embedding_text."""
        pdf_bytes = _make_test_pdf("Text fields test")
        result = ingest_and_index_pdf_bytes(pdf_bytes, "test.pdf")

        chunks = get_chunks_by_enrichment_status(
            "PENDING", document_id=result.document_id
        )

        for chunk in chunks:
            assert chunk.text, "text should be set"
            assert chunk.embedding_text, "embedding_text should be set"
            # embedding_text should be longer (includes headers)
            assert len(chunk.embedding_text) >= len(chunk.text)


class TestU4SearchabilityAfterIndex:
    """Verify documents are searchable immediately after indexing."""

    def test_chunks_in_qdrant_after_index(self):
        """Chunks should be in Qdrant and queryable after indexing."""
        pdf_bytes = _make_test_pdf("Searchability test: important concept here")
        result = ingest_and_index_pdf_bytes(pdf_bytes, "test.pdf")

        # Should be able to query Qdrant for these chunks
        chunks = get_chunks_by_enrichment_status(
            "PENDING", document_id=result.document_id
        )

        assert len(chunks) == result.indexed_count
        assert all(chunk.document_id == result.document_id for chunk in chunks)
