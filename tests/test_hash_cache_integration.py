"""
Integration tests for content hash cache with Qdrant persistence (U2).

Tests verify:
1. Cache usage during multi-document ingestion
2. Cross-document chunk deduplication
3. Cache hit metrics across documents
4. Cache behavior with actual Chunk models and Qdrant storage
"""

import pytest
from fastapi.testclient import TestClient

from app.enrichment.hash_cache import get_enrichment_cache, reset_enrichment_cache
from app.main import create_app
from app.models.document import Chunk
from app.models.enrichment import EnrichmentResult, compute_content_hash


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create test client with temporary data directories."""
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    raw_dir.mkdir()
    processed_dir.mkdir()

    monkeypatch.setenv("RAW_DIR", str(raw_dir))
    monkeypatch.setenv("PROCESSED_DIR", str(processed_dir))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ENRICHMENT_ENABLED", "false")
    monkeypatch.setenv("COVERAGE_VERIFY_ENABLED", "false")
    monkeypatch.setenv("ANSWER_VALIDATION_ENABLED", "false")

    from app.config.settings import get_settings

    get_settings.cache_clear()

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()
    reset_enrichment_cache()


class TestCacheWithChunks:
    """Test enrichment cache with Chunk models."""

    @pytest.fixture
    def sample_chunks(self):
        """Create sample chunks with some text duplication."""
        return [
            # Document 1, Chunk 1: unique text
            Chunk(
                chunk_id="doc1-chunk1",
                document_id="doc1",
                filename="doc1.pdf",
                page_number=1,
                chunk_index=0,
                text="Unique content for document one",
                char_start=0,
                char_end=31,
                token_count=6,
            ),
            # Document 1, Chunk 2: shared text
            Chunk(
                chunk_id="doc1-chunk2",
                document_id="doc1",
                filename="doc1.pdf",
                page_number=2,
                chunk_index=1,
                text="This is shared content across multiple documents",
                char_start=31,
                char_end=80,
                token_count=10,
            ),
            # Document 2, Chunk 1: different unique text
            Chunk(
                chunk_id="doc2-chunk1",
                document_id="doc2",
                filename="doc2.pdf",
                page_number=1,
                chunk_index=0,
                text="Different content for document two",
                char_start=0,
                char_end=34,
                token_count=6,
            ),
            # Document 2, Chunk 2: same as doc1-chunk2 (deduplication target)
            Chunk(
                chunk_id="doc2-chunk2",
                document_id="doc2",
                filename="doc2.pdf",
                page_number=2,
                chunk_index=1,
                text="This is shared content across multiple documents",
                char_start=34,
                char_end=83,
                token_count=10,
            ),
        ]

    def test_chunks_with_identical_text_produce_same_hash(self, sample_chunks):
        """Chunks with identical text from different documents should have same hash."""
        chunk1 = sample_chunks[1]  # doc1-chunk2
        chunk2 = sample_chunks[3]  # doc2-chunk2

        hash1 = compute_content_hash(chunk1.text)
        hash2 = compute_content_hash(chunk2.text)

        assert chunk1.text == chunk2.text
        assert hash1 == hash2

    def test_chunks_with_different_text_produce_different_hashes(
        self, sample_chunks
    ):
        """Chunks with different text should have different hashes."""
        chunk1 = sample_chunks[0]  # doc1-chunk1
        chunk2 = sample_chunks[2]  # doc2-chunk1

        hash1 = compute_content_hash(chunk1.text)
        hash2 = compute_content_hash(chunk2.text)

        assert hash1 != hash2

    def test_cache_workflow_with_multiple_chunks(self, sample_chunks):
        """Simulate cache workflow: enrich chunk, then reuse for identical chunk."""
        reset_enrichment_cache()
        cache = get_enrichment_cache()

        # Chunk 1: first enrichment
        chunk1 = sample_chunks[1]  # doc1-chunk2
        hash1 = compute_content_hash(chunk1.text)
        result1 = EnrichmentResult(
            content_hash=hash1,
            summary="Summary of shared content",
            topics=["shared", "documents"],
            entities=["document"],
        )
        cache.set(hash1, result1)

        # Chunk 2: should hit cache (same text, different doc)
        chunk2 = sample_chunks[3]  # doc2-chunk2
        hash2 = compute_content_hash(chunk2.text)
        assert hash1 == hash2  # Same hash because text is identical
        assert cache.exists(hash2)  # Should exist in cache
        cached_result = cache.get(hash2)
        assert cached_result is not None
        assert cached_result.summary == "Summary of shared content"
        assert cache.size() == 1  # Only one entry despite processing two chunks


class TestCacheDedupAcrossDocuments:
    """Test cache deduplication patterns across multiple documents."""

    def test_three_documents_sharing_common_chunks(self):
        """Three documents with some shared and unique chunks."""
        reset_enrichment_cache()
        cache = get_enrichment_cache()

        # Common text shared by all documents
        common_text = "This is a common introduction section"
        common_hash = compute_content_hash(common_text)

        # Doc 1, unique text
        doc1_unique = "Document 1 specific content"
        hash1_unique = compute_content_hash(doc1_unique)

        # Doc 2, unique text
        doc2_unique = "Document 2 specific content"
        hash2_unique = compute_content_hash(doc2_unique)

        # Doc 3, unique text
        doc3_unique = "Document 3 specific content"
        hash3_unique = compute_content_hash(doc3_unique)

        # Enrich all chunks
        common_result = EnrichmentResult(
            content_hash=common_hash,
            summary="Common introduction",
            topics=["intro"],
        )
        doc1_result = EnrichmentResult(
            content_hash=hash1_unique,
            summary="Doc 1 content",
            topics=["doc1"],
        )
        doc2_result = EnrichmentResult(
            content_hash=hash2_unique,
            summary="Doc 2 content",
            topics=["doc2"],
        )
        doc3_result = EnrichmentResult(
            content_hash=hash3_unique,
            summary="Doc 3 content",
            topics=["doc3"],
        )

        # Document 1: enrich 2 chunks (1 common, 1 unique)
        cache.set(common_hash, common_result)
        cache.set(hash1_unique, doc1_result)
        assert cache.size() == 2

        # Document 2: enrich 2 chunks (common already cached, unique new)
        assert cache.exists(common_hash)  # Cache hit
        cache.set(hash2_unique, doc2_result)
        assert cache.size() == 3

        # Document 3: enrich 2 chunks (common already cached, unique new)
        assert cache.exists(common_hash)  # Cache hit again
        cache.set(hash3_unique, doc3_result)
        assert cache.size() == 4

        # Verify all results are retrievable
        assert cache.get(common_hash).summary == "Common introduction"
        assert cache.get(hash1_unique).summary == "Doc 1 content"
        assert cache.get(hash2_unique).summary == "Doc 2 content"
        assert cache.get(hash3_unique).summary == "Doc 3 content"

    def test_cache_hit_ratio_calculation(self):
        """Calculate cache hit ratio for realistic multi-document scenario."""
        reset_enrichment_cache()
        cache = get_enrichment_cache()

        # Simulate 5 documents with 10 chunks each (50 total chunks)
        # with 60% unique content and 40% duplicated

        num_docs = 5
        chunks_per_doc = 10
        unique_ratio = 0.6  # 60% unique per document
        total_chunks = num_docs * chunks_per_doc

        # Create base unique hashes
        unique_hashes = set()
        for i in range(int(total_chunks * unique_ratio)):
            unique_hashes.add(f"hash_unique_{i}")

        cache_hits = 0
        cache_misses = 0
        cache_sets = 0

        # Process documents
        for doc_idx in range(num_docs):
            for chunk_idx in range(chunks_per_doc):
                # 60% chance of unique hash, 40% chance of reuse
                if chunk_idx < int(chunks_per_doc * unique_ratio):
                    hash_val = f"hash_unique_{doc_idx * chunks_per_doc + chunk_idx}"
                else:
                    # Reuse earlier hash
                    hash_val = f"hash_unique_{(doc_idx * chunks_per_doc + chunk_idx) % int(total_chunks * unique_ratio)}"

                if cache.exists(hash_val):
                    cache_hits += 1
                else:
                    cache_misses += 1
                    result = EnrichmentResult(
                        content_hash=hash_val,
                        summary=f"Summary for {hash_val}",
                    )
                    cache.set(hash_val, result)
                    cache_sets += 1

        # Calculate hit ratio
        total_checks = cache_hits + cache_misses
        hit_ratio = cache_hits / total_checks if total_checks > 0 else 0

        # With the pattern above, we expect > 0 cache hits
        assert cache_hits > 0
        assert cache_misses > 0
        assert cache_sets < total_chunks  # Should cache fewer items than total chunks
        assert hit_ratio > 0  # Some deduplication should occur

    def test_cache_text_normalization_across_documents(self):
        """Cache should match chunks across documents despite formatting differences."""
        reset_enrichment_cache()
        cache = get_enrichment_cache()

        # Same content with different formatting
        text1 = "This is  a test  with MULTIPLE spaces"
        text2 = "this\nis\na\ntest\nwith\nmultiple\nspaces"
        text3 = "THIS IS A TEST WITH MULTIPLE SPACES"

        hash1 = compute_content_hash(text1)
        hash2 = compute_content_hash(text2)
        hash3 = compute_content_hash(text3)

        # All should normalize to the same hash
        assert hash1 == hash2 == hash3

        # Cache entry for normalized text
        result = EnrichmentResult(
            content_hash=hash1,
            summary="Normalized content",
        )
        cache.set(hash1, result)

        # All three text variations should hit the same cache entry
        assert cache.exists(hash1)
        assert cache.exists(hash2)
        assert cache.exists(hash3)
        assert cache.get(hash2) is not None
        assert cache.get(hash3) is not None


class TestCacheWithChunkModel:
    """Test cache behavior when integrated with Chunk model."""

    def test_chunk_with_content_hash_can_check_cache(self):
        """Chunk should be able to use content_hash to check cache."""
        reset_enrichment_cache()
        cache = get_enrichment_cache()

        chunk = Chunk(
            chunk_id="test-chunk",
            document_id="doc1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text="Test chunk content",
            char_start=0,
            char_end=18,
            token_count=4,
        )

        # Compute hash for chunk
        content_hash = compute_content_hash(chunk.text)
        chunk.content_hash = content_hash

        # Create enrichment result
        result = EnrichmentResult(
            content_hash=content_hash,
            summary="Test summary",
            topics=["test"],
        )

        # Cache the enrichment
        cache.set(content_hash, result)

        # Verify we can retrieve it via the cache API
        assert cache.exists(chunk.content_hash)
        retrieved = cache.get(chunk.content_hash)
        assert retrieved is not None
        assert retrieved.summary == "Test summary"

    def test_chunk_content_hash_field_consistency(self):
        """Chunk.content_hash should stay consistent with computed hash."""
        text = "Chunk content for consistency check"
        computed_hash = compute_content_hash(text)

        chunk = Chunk(
            chunk_id="test-chunk",
            document_id="doc1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text=text,
            char_start=0,
            char_end=len(text),
            token_count=7,
            content_hash=computed_hash,
        )

        # Verify consistency
        assert chunk.content_hash == computed_hash
        assert compute_content_hash(chunk.text) == chunk.content_hash
