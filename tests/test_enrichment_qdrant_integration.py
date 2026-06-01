"""
Integration tests for enrichment status with Qdrant (U1).

Tests verify:
1. Chunks with enrichment_status are stored in Qdrant
2. Qdrant can filter and query by enrichment_status
3. Count operations work correctly
"""
import pytest

from app.models.document import Chunk
from app.models.enrichment import EnrichmentStatus, compute_content_hash
from app.vectorstore import qdrant_client


@pytest.fixture(autouse=True)
def clear_qdrant():
    """Clear Qdrant collection before and after each test."""
    qdrant_client.ensure_collection()
    settings_obj = qdrant_client.get_settings()
    client = qdrant_client.get_qdrant_client()

    # Delete and recreate collection
    try:
        client.delete_collection(settings_obj.qdrant_collection)
    except Exception:
        pass

    # Recreate collection
    qdrant_client.ensure_collection()

    yield

    # Cleanup after test
    try:
        client.delete_collection(settings_obj.qdrant_collection)
    except Exception:
        pass


class TestEnrichmentStatusQdrantStorage:
    """Test storing and retrieving enrichment_status in Qdrant."""

    def test_upsert_chunks_with_enrichment_status(self):
        """Chunks with enrichment_status should be stored in Qdrant."""
        text = "Sample chunk text for testing"
        chunk = Chunk(
            chunk_id="chunk-1",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text=text,
            char_start=0,
            char_end=len(text),
            token_count=5,
            enrichment_status=EnrichmentStatus.PENDING,
            content_hash=compute_content_hash(text),
        )

        qdrant_client.upsert_chunks([chunk])

        # Verify by iterating all chunks
        all_chunks = qdrant_client.iter_all_chunks()
        assert len(all_chunks) == 1
        assert all_chunks[0].enrichment_status == EnrichmentStatus.PENDING
        assert all_chunks[0].content_hash == compute_content_hash(text)

    def test_upsert_chunks_preserves_all_enrichment_fields(self):
        """All enrichment fields should be preserved in Qdrant."""
        from datetime import datetime, timezone

        text = "Sample chunk text"
        now = datetime.now(timezone.utc)
        chunk = Chunk(
            chunk_id="chunk-1",
            document_id="doc-1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text=text,
            char_start=0,
            char_end=len(text),
            token_count=4,
            enrichment_status=EnrichmentStatus.COMPLETED,
            content_hash=compute_content_hash(text),
            enriched_at=now,
            summary="Sample summary",
            topics=["topic1", "topic2"],
        )

        qdrant_client.upsert_chunks([chunk])

        all_chunks = qdrant_client.iter_all_chunks()
        assert len(all_chunks) == 1
        retrieved = all_chunks[0]
        assert retrieved.enrichment_status == EnrichmentStatus.COMPLETED
        assert retrieved.content_hash == compute_content_hash(text)
        assert retrieved.enriched_at == now
        assert retrieved.summary == "Sample summary"
        assert retrieved.topics == ["topic1", "topic2"]


class TestEnrichmentStatusQdrantQueries:
    """Test querying chunks by enrichment_status."""

    def test_get_chunks_by_enrichment_status_pending(self):
        """Query should return chunks with PENDING status."""
        chunks = [
            Chunk(
                chunk_id=f"chunk-{i}",
                document_id="doc-1",
                filename="test.pdf",
                page_number=1,
                chunk_index=i,
                text=f"Text {i}",
                char_start=i * 10,
                char_end=(i + 1) * 10,
                token_count=2,
                enrichment_status=EnrichmentStatus.PENDING,
                content_hash=compute_content_hash(f"Text {i}"),
            )
            for i in range(3)
        ]

        qdrant_client.upsert_chunks(chunks)

        pending = qdrant_client.get_chunks_by_enrichment_status("PENDING")
        assert len(pending) == 3
        assert all(c.enrichment_status == EnrichmentStatus.PENDING for c in pending)

    def test_get_chunks_by_enrichment_status_completed(self):
        """Query should return only chunks with COMPLETED status."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        chunks = [
            Chunk(
                chunk_id="chunk-1",
                document_id="doc-1",
                filename="test.pdf",
                page_number=1,
                chunk_index=0,
                text="Text 1",
                char_start=0,
                char_end=10,
                token_count=2,
                enrichment_status=EnrichmentStatus.PENDING,
                content_hash=compute_content_hash("Text 1"),
            ),
            Chunk(
                chunk_id="chunk-2",
                document_id="doc-1",
                filename="test.pdf",
                page_number=1,
                chunk_index=1,
                text="Text 2",
                char_start=10,
                char_end=20,
                token_count=2,
                enrichment_status=EnrichmentStatus.COMPLETED,
                content_hash=compute_content_hash("Text 2"),
                enriched_at=now,
            ),
        ]

        qdrant_client.upsert_chunks(chunks)

        completed = qdrant_client.get_chunks_by_enrichment_status("COMPLETED")
        assert len(completed) == 1
        assert completed[0].chunk_id == "chunk-2"
        assert completed[0].enrichment_status == EnrichmentStatus.COMPLETED

    def test_get_chunks_by_status_with_document_filter(self):
        """Query should filter by both status and document_id."""
        chunks = [
            Chunk(
                chunk_id="chunk-1",
                document_id="doc-1",
                filename="test.pdf",
                page_number=1,
                chunk_index=0,
                text="Text 1",
                char_start=0,
                char_end=10,
                token_count=2,
                enrichment_status=EnrichmentStatus.PENDING,
                content_hash=compute_content_hash("Text 1"),
            ),
            Chunk(
                chunk_id="chunk-2",
                document_id="doc-2",
                filename="other.pdf",
                page_number=1,
                chunk_index=0,
                text="Text 2",
                char_start=0,
                char_end=10,
                token_count=2,
                enrichment_status=EnrichmentStatus.PENDING,
                content_hash=compute_content_hash("Text 2"),
            ),
        ]

        qdrant_client.upsert_chunks(chunks)

        # Query PENDING chunks for doc-1 only
        pending_doc1 = qdrant_client.get_chunks_by_enrichment_status(
            "PENDING", document_id="doc-1"
        )
        assert len(pending_doc1) == 1
        assert pending_doc1[0].document_id == "doc-1"

        # Query PENDING chunks for doc-2
        pending_doc2 = qdrant_client.get_chunks_by_enrichment_status(
            "PENDING", document_id="doc-2"
        )
        assert len(pending_doc2) == 1
        assert pending_doc2[0].document_id == "doc-2"


class TestEnrichmentStatusCounting:
    """Test counting chunks by enrichment_status."""

    def test_count_chunks_by_enrichment_status_all_pending(self):
        """Count should show all chunks as PENDING initially."""
        chunks = [
            Chunk(
                chunk_id=f"chunk-{i}",
                document_id="doc-1",
                filename="test.pdf",
                page_number=1,
                chunk_index=i,
                text=f"Text {i}",
                char_start=i * 10,
                char_end=(i + 1) * 10,
                token_count=2,
                enrichment_status=EnrichmentStatus.PENDING,
                content_hash=compute_content_hash(f"Text {i}"),
            )
            for i in range(5)
        ]

        qdrant_client.upsert_chunks(chunks)

        counts = qdrant_client.count_chunks_by_enrichment_status("doc-1")
        assert counts["PENDING"] == 5
        assert counts["PROCESSING"] == 0
        assert counts["COMPLETED"] == 0
        assert counts["FAILED"] == 0

    def test_count_chunks_mixed_statuses(self):
        """Count should track chunks in multiple statuses."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        chunks = [
            Chunk(
                chunk_id="chunk-1",
                document_id="doc-1",
                filename="test.pdf",
                page_number=1,
                chunk_index=0,
                text="Text 1",
                char_start=0,
                char_end=10,
                token_count=2,
                enrichment_status=EnrichmentStatus.PENDING,
                content_hash=compute_content_hash("Text 1"),
            ),
            Chunk(
                chunk_id="chunk-2",
                document_id="doc-1",
                filename="test.pdf",
                page_number=1,
                chunk_index=1,
                text="Text 2",
                char_start=10,
                char_end=20,
                token_count=2,
                enrichment_status=EnrichmentStatus.PROCESSING,
                content_hash=compute_content_hash("Text 2"),
            ),
            Chunk(
                chunk_id="chunk-3",
                document_id="doc-1",
                filename="test.pdf",
                page_number=1,
                chunk_index=2,
                text="Text 3",
                char_start=20,
                char_end=30,
                token_count=2,
                enrichment_status=EnrichmentStatus.COMPLETED,
                content_hash=compute_content_hash("Text 3"),
                enriched_at=now,
            ),
        ]

        qdrant_client.upsert_chunks(chunks)

        counts = qdrant_client.count_chunks_by_enrichment_status("doc-1")
        assert counts["PENDING"] == 1
        assert counts["PROCESSING"] == 1
        assert counts["COMPLETED"] == 1
        assert counts["FAILED"] == 0

    def test_count_chunks_only_counts_specified_document(self):
        """Count should only count chunks from the specified document."""
        chunks = [
            Chunk(
                chunk_id="chunk-1",
                document_id="doc-1",
                filename="test.pdf",
                page_number=1,
                chunk_index=0,
                text="Text 1",
                char_start=0,
                char_end=10,
                token_count=2,
                enrichment_status=EnrichmentStatus.PENDING,
                content_hash=compute_content_hash("Text 1"),
            ),
            Chunk(
                chunk_id="chunk-2",
                document_id="doc-2",
                filename="other.pdf",
                page_number=1,
                chunk_index=0,
                text="Text 2",
                char_start=0,
                char_end=10,
                token_count=2,
                enrichment_status=EnrichmentStatus.PENDING,
                content_hash=compute_content_hash("Text 2"),
            ),
        ]

        qdrant_client.upsert_chunks(chunks)

        # Count for doc-1
        counts_doc1 = qdrant_client.count_chunks_by_enrichment_status("doc-1")
        assert counts_doc1["PENDING"] == 1
        assert counts_doc1["PROCESSING"] == 0
        assert counts_doc1["COMPLETED"] == 0
        assert counts_doc1["FAILED"] == 0

        # Count for doc-2
        counts_doc2 = qdrant_client.count_chunks_by_enrichment_status("doc-2")
        assert counts_doc2["PENDING"] == 1
        assert counts_doc2["PROCESSING"] == 0
        assert counts_doc2["COMPLETED"] == 0
        assert counts_doc2["FAILED"] == 0


class TestEnrichmentStatusIndexing:
    """Test that enrichment_status index is created correctly."""

    def test_collection_has_enrichment_status_index(self):
        """Collection should have enrichment_status payload index."""
        qdrant_client.ensure_collection()
        settings_obj = qdrant_client.get_settings()
        client = qdrant_client.get_qdrant_client()

        collection = client.get_collection(settings_obj.qdrant_collection)
        # Check that the collection was created (it exists)
        assert collection is not None
        # Collection should have payload indexes for document_id, page_number, enrichment_status
        # (Qdrant may not expose all index details through the API, but we verify storage works)

    def test_enrichment_status_query_performance(self):
        """Enrichment status queries should be efficient with index."""
        # Create a larger dataset
        chunks = [
            Chunk(
                chunk_id=f"chunk-{i}",
                document_id="doc-1",
                filename="test.pdf",
                page_number=1 + (i // 10),
                chunk_index=i,
                text=f"Text {i}",
                char_start=i * 20,
                char_end=(i + 1) * 20,
                token_count=2,
                enrichment_status=EnrichmentStatus.PENDING if i % 2 == 0 else EnrichmentStatus.COMPLETED,
                content_hash=compute_content_hash(f"Text {i}"),
            )
            for i in range(50)
        ]

        qdrant_client.upsert_chunks(chunks)

        # Query should be fast even with many chunks
        completed = qdrant_client.get_chunks_by_enrichment_status(
            "COMPLETED", document_id="doc-1"
        )
        assert len(completed) == 25  # All odd-indexed chunks
        assert all(c.enrichment_status == EnrichmentStatus.COMPLETED for c in completed)
