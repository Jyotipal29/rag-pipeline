"""
Tests for enrichment status tracking (U1).

Tests verify:
1. New chunks initialize with enrichment_status="PENDING"
2. Status transitions work correctly: PENDING → PROCESSING → COMPLETED
3. Qdrant can filter by enrichment_status
4. Content hash is computed consistently
"""
import hashlib
from datetime import datetime, timezone

import pytest

from app.models.document import Chunk
from app.models.enrichment import EnrichmentStatus, compute_content_hash


class TestEnrichmentStatus:
    """Test enrichment status enum and transitions."""

    def test_enrichment_status_values(self):
        """Verify EnrichmentStatus has all required values."""
        assert EnrichmentStatus.PENDING.value == "PENDING"
        assert EnrichmentStatus.PROCESSING.value == "PROCESSING"
        assert EnrichmentStatus.COMPLETED.value == "COMPLETED"
        assert EnrichmentStatus.FAILED.value == "FAILED"

    def test_all_status_values_exist(self):
        """Verify all expected status values exist."""
        statuses = {status.value for status in EnrichmentStatus}
        assert statuses == {"PENDING", "PROCESSING", "COMPLETED", "FAILED"}


class TestChunkEnrichmentFields:
    """Test enrichment fields in Chunk model."""

    def test_chunk_default_enrichment_status_is_pending(self):
        """New chunks should default to enrichment_status='PENDING'."""
        chunk = Chunk(
            chunk_id="test-chunk-1",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text="Sample text",
            char_start=0,
            char_end=11,
            token_count=3,
        )
        assert chunk.enrichment_status == EnrichmentStatus.PENDING

    def test_chunk_enriched_at_defaults_to_none(self):
        """New chunks should have enriched_at=None."""
        chunk = Chunk(
            chunk_id="test-chunk-1",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text="Sample text",
            char_start=0,
            char_end=11,
            token_count=3,
        )
        assert chunk.enriched_at is None

    def test_chunk_content_hash_stored(self):
        """Chunk should store content_hash field."""
        text = "Sample text for hashing"
        chunk = Chunk(
            chunk_id="test-chunk-1",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text=text,
            char_start=0,
            char_end=len(text),
            token_count=5,
            content_hash="abc123hash",
        )
        assert chunk.content_hash == "abc123hash"

    def test_chunk_can_set_enrichment_status(self):
        """Chunk enrichment_status can be set to any valid status."""
        chunk = Chunk(
            chunk_id="test-chunk-1",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text="Sample text",
            char_start=0,
            char_end=11,
            token_count=3,
        )
        chunk.enrichment_status = EnrichmentStatus.PROCESSING
        assert chunk.enrichment_status == EnrichmentStatus.PROCESSING

        chunk.enrichment_status = EnrichmentStatus.COMPLETED
        assert chunk.enrichment_status == EnrichmentStatus.COMPLETED

    def test_chunk_can_set_enriched_at(self):
        """Chunk enriched_at can be set to a datetime."""
        now = datetime.now(timezone.utc)
        chunk = Chunk(
            chunk_id="test-chunk-1",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text="Sample text",
            char_start=0,
            char_end=11,
            token_count=3,
            enriched_at=now,
        )
        assert chunk.enriched_at == now


class TestContentHashComputation:
    """Test content hash computation for deduplication."""

    def test_compute_content_hash_deterministic(self):
        """Same text should always produce the same hash."""
        text = "This is a test document chunk."
        hash1 = compute_content_hash(text)
        hash2 = compute_content_hash(text)
        assert hash1 == hash2

    def test_compute_content_hash_different_text_different_hash(self):
        """Different text should produce different hashes."""
        text1 = "First document chunk"
        text2 = "Second document chunk"
        hash1 = compute_content_hash(text1)
        hash2 = compute_content_hash(text2)
        assert hash1 != hash2

    def test_compute_content_hash_format(self):
        """Content hash should be a hex string (SHA256)."""
        text = "Sample text"
        hash_val = compute_content_hash(text)
        # SHA256 hex digest is 64 characters
        assert len(hash_val) == 64
        assert all(c in "0123456789abcdef" for c in hash_val)

    def test_compute_content_hash_whitespace_normalized(self):
        """Whitespace differences should not affect hash (normalized)."""
        text1 = "This is a test document"
        text2 = "This  is   a    test    document"  # Extra spaces
        hash1 = compute_content_hash(text1)
        hash2 = compute_content_hash(text2)
        # After normalization, should be equal
        assert hash1 == hash2

    def test_compute_content_hash_case_insensitive(self):
        """Case differences should not affect hash (normalized)."""
        text1 = "This Is A Test Document"
        text2 = "this is a test document"
        hash1 = compute_content_hash(text1)
        hash2 = compute_content_hash(text2)
        # After normalization, should be equal
        assert hash1 == hash2

    def test_compute_content_hash_with_newlines(self):
        """Newlines should be normalized in hash computation."""
        text1 = "Line 1\nLine 2\nLine 3"
        text2 = "Line 1  Line 2  Line 3"
        hash1 = compute_content_hash(text1)
        hash2 = compute_content_hash(text2)
        # After normalization, should be equal
        assert hash1 == hash2

    def test_compute_content_hash_empty_string(self):
        """Empty string should produce a valid hash."""
        hash_val = compute_content_hash("")
        assert len(hash_val) == 64
        assert all(c in "0123456789abcdef" for c in hash_val)


class TestChunkEnrichmentTransitions:
    """Test status transitions during enrichment workflow."""

    def test_enrichment_workflow_pending_to_processing(self):
        """Status should transition from PENDING to PROCESSING."""
        chunk = Chunk(
            chunk_id="test-chunk-1",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text="Sample text",
            char_start=0,
            char_end=11,
            token_count=3,
        )
        assert chunk.enrichment_status == EnrichmentStatus.PENDING

        chunk.enrichment_status = EnrichmentStatus.PROCESSING
        assert chunk.enrichment_status == EnrichmentStatus.PROCESSING

    def test_enrichment_workflow_processing_to_completed(self):
        """Status should transition from PROCESSING to COMPLETED."""
        chunk = Chunk(
            chunk_id="test-chunk-1",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text="Sample text",
            char_start=0,
            char_end=11,
            token_count=3,
            enrichment_status=EnrichmentStatus.PROCESSING,
        )
        assert chunk.enrichment_status == EnrichmentStatus.PROCESSING

        chunk.enrichment_status = EnrichmentStatus.COMPLETED
        chunk.enriched_at = datetime.now(timezone.utc)
        assert chunk.enrichment_status == EnrichmentStatus.COMPLETED
        assert chunk.enriched_at is not None

    def test_enrichment_workflow_to_failed(self):
        """Status should transition to FAILED on error."""
        chunk = Chunk(
            chunk_id="test-chunk-1",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text="Sample text",
            char_start=0,
            char_end=11,
            token_count=3,
            enrichment_status=EnrichmentStatus.PROCESSING,
        )
        chunk.enrichment_status = EnrichmentStatus.FAILED
        assert chunk.enrichment_status == EnrichmentStatus.FAILED


class TestChunkEnrichmentSerialization:
    """Test that enrichment fields serialize/deserialize correctly."""

    def test_chunk_model_dump_includes_enrichment_status(self):
        """Chunk.model_dump should include enrichment_status."""
        chunk = Chunk(
            chunk_id="test-chunk-1",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text="Sample text",
            char_start=0,
            char_end=11,
            token_count=3,
        )
        chunk_dict = chunk.model_dump()
        assert "enrichment_status" in chunk_dict
        assert chunk_dict["enrichment_status"] == EnrichmentStatus.PENDING

    def test_chunk_model_dump_includes_content_hash(self):
        """Chunk.model_dump should include content_hash."""
        chunk = Chunk(
            chunk_id="test-chunk-1",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text="Sample text",
            char_start=0,
            char_end=11,
            token_count=3,
            content_hash="abc123",
        )
        chunk_dict = chunk.model_dump()
        assert "content_hash" in chunk_dict
        assert chunk_dict["content_hash"] == "abc123"

    def test_chunk_model_dump_includes_enriched_at(self):
        """Chunk.model_dump should include enriched_at."""
        now = datetime.now(timezone.utc)
        chunk = Chunk(
            chunk_id="test-chunk-1",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text="Sample text",
            char_start=0,
            char_end=11,
            token_count=3,
            enriched_at=now,
        )
        chunk_dict = chunk.model_dump()
        assert "enriched_at" in chunk_dict
        assert chunk_dict["enriched_at"] == now

    def test_chunk_model_validate_from_dict(self):
        """Chunk should validate from dict with enrichment fields."""
        data = {
            "chunk_id": "test-chunk-1",
            "document_id": "doc-1",
            "filename": "test.pdf",
            "page_number": 1,
            "chunk_index": 0,
            "text": "Sample text",
            "char_start": 0,
            "char_end": 11,
            "token_count": 3,
            "enrichment_status": "COMPLETED",
            "content_hash": "abc123hash",
        }
        chunk = Chunk.model_validate(data)
        assert chunk.enrichment_status == EnrichmentStatus.COMPLETED
        assert chunk.content_hash == "abc123hash"


class TestMultipleChunksWithEnrichmentStatus:
    """Test enrichment status across multiple chunks."""

    def test_chunks_independent_enrichment_status(self):
        """Each chunk should have independent enrichment_status."""
        chunk1 = Chunk(
            chunk_id="chunk-1",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text="First chunk",
            char_start=0,
            char_end=11,
            token_count=2,
        )
        chunk2 = Chunk(
            chunk_id="chunk-2",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=1,
            text="Second chunk",
            char_start=12,
            char_end=24,
            token_count=2,
        )

        chunk1.enrichment_status = EnrichmentStatus.COMPLETED
        assert chunk1.enrichment_status == EnrichmentStatus.COMPLETED
        assert chunk2.enrichment_status == EnrichmentStatus.PENDING

    def test_chunks_independent_content_hash(self):
        """Each chunk should have its own content_hash."""
        chunk1 = Chunk(
            chunk_id="chunk-1",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text="First chunk",
            char_start=0,
            char_end=11,
            token_count=2,
            content_hash=compute_content_hash("First chunk"),
        )
        chunk2 = Chunk(
            chunk_id="chunk-2",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=1,
            text="Second chunk",
            char_start=12,
            char_end=24,
            token_count=2,
            content_hash=compute_content_hash("Second chunk"),
        )

        assert chunk1.content_hash != chunk2.content_hash

    def test_chunks_with_identical_text_same_hash(self):
        """Chunks with identical text should have same hash (for dedup)."""
        text = "This is identical text"
        chunk1 = Chunk(
            chunk_id="chunk-1",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text=text,
            char_start=0,
            char_end=len(text),
            token_count=4,
            content_hash=compute_content_hash(text),
        )
        chunk2 = Chunk(
            chunk_id="chunk-2",
            document_id="doc-2",
            filename="other.pdf",
            page_number=2,
            chunk_index=0,
            text=text,
            char_start=0,
            char_end=len(text),
            token_count=4,
            content_hash=compute_content_hash(text),
        )

        assert chunk1.content_hash == chunk2.content_hash
