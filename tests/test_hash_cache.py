"""
Tests for content hash caching layer (U2).

Tests verify:
1. Hash computation is deterministic (same text → same hash)
2. Cache hit when identical chunk text exists
3. Cache miss when chunk text is unique
4. Cache reuse across different documents with same chunk text
5. Cache persists correctly and operations are valid
"""

from datetime import datetime, timezone

import pytest

from app.enrichment.hash_cache import (
    EnrichmentCache,
    get_enrichment_cache,
    reset_enrichment_cache,
)
from app.models.enrichment import EnrichmentResult, compute_content_hash


class TestContentHashComputation:
    """Test deterministic content hash computation."""

    def test_hash_is_deterministic_same_text_same_hash(self):
        """Same text should always produce the same hash."""
        text = "This is sample text for hashing"
        hash1 = compute_content_hash(text)
        hash2 = compute_content_hash(text)
        assert hash1 == hash2

    def test_hash_is_case_insensitive(self):
        """Case should not affect hash (normalization)."""
        hash_lower = compute_content_hash("hello world")
        hash_upper = compute_content_hash("HELLO WORLD")
        hash_mixed = compute_content_hash("HeLLo WoRLd")
        assert hash_lower == hash_upper == hash_mixed

    def test_hash_normalizes_whitespace(self):
        """Multiple spaces/tabs/newlines should normalize to single space."""
        hash1 = compute_content_hash("hello    world")
        hash2 = compute_content_hash("hello\t\tworld")
        hash3 = compute_content_hash("hello\n\nworld")
        hash4 = compute_content_hash("hello world")
        assert hash1 == hash2 == hash3 == hash4

    def test_hash_ignores_leading_trailing_whitespace(self):
        """Leading/trailing whitespace should be stripped."""
        hash1 = compute_content_hash("   hello world   ")
        hash2 = compute_content_hash("hello world")
        assert hash1 == hash2

    def test_hash_produces_64_char_hex_string(self):
        """SHA256 hash should be 64 hex characters."""
        text = "test content"
        h = compute_content_hash(text)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_text_produces_different_hashes(self):
        """Different text should produce different hashes."""
        hash1 = compute_content_hash("text one")
        hash2 = compute_content_hash("text two")
        assert hash1 != hash2

    def test_empty_string_produces_hash(self):
        """Even empty string should produce a valid hash."""
        h = compute_content_hash("")
        assert len(h) == 64
        assert isinstance(h, str)


class TestEnrichmentCache:
    """Test EnrichmentCache functionality."""

    @pytest.fixture
    def cache(self):
        """Create a fresh cache for each test."""
        return EnrichmentCache()

    @pytest.fixture
    def sample_result(self):
        """Create a sample EnrichmentResult for testing."""
        return EnrichmentResult(
            content_hash="abc123",
            summary="This is a test summary.",
            topics=["topic1", "topic2"],
            entities=["entity1"],
        )

    def test_cache_initialized_empty(self, cache):
        """New cache should be empty."""
        assert cache.size() == 0
        assert cache.stats() == {"size": 0}

    def test_cache_get_returns_none_for_missing_hash(self, cache):
        """Get on non-existent hash should return None."""
        result = cache.get("nonexistent_hash")
        assert result is None

    def test_cache_set_stores_result(self, cache, sample_result):
        """Set should store result in cache."""
        cache.set(sample_result.content_hash, sample_result)
        assert cache.size() == 1

    def test_cache_get_returns_cached_result(self, cache, sample_result):
        """Get should return previously set result."""
        cache.set(sample_result.content_hash, sample_result)
        retrieved = cache.get(sample_result.content_hash)
        assert retrieved is not None
        assert retrieved.summary == sample_result.summary
        assert retrieved.topics == sample_result.topics
        assert retrieved.entities == sample_result.entities

    def test_cache_exists_returns_true_for_cached_hash(self, cache, sample_result):
        """Exists should return True for cached hash."""
        cache.set(sample_result.content_hash, sample_result)
        assert cache.exists(sample_result.content_hash) is True

    def test_cache_exists_returns_false_for_missing_hash(self, cache):
        """Exists should return False for non-cached hash."""
        assert cache.exists("nonexistent") is False

    def test_cache_multiple_entries(self, cache):
        """Cache should hold multiple entries independently."""
        result1 = EnrichmentResult(
            content_hash="hash1",
            summary="Summary 1",
            topics=["topic1"],
        )
        result2 = EnrichmentResult(
            content_hash="hash2",
            summary="Summary 2",
            topics=["topic2"],
        )
        cache.set("hash1", result1)
        cache.set("hash2", result2)
        assert cache.size() == 2
        assert cache.get("hash1").summary == "Summary 1"
        assert cache.get("hash2").summary == "Summary 2"

    def test_cache_overwrite_replaces_entry(self, cache):
        """Setting same hash twice should replace entry."""
        result1 = EnrichmentResult(
            content_hash="hash1",
            summary="Original summary",
        )
        result2 = EnrichmentResult(
            content_hash="hash1",
            summary="Updated summary",
        )
        cache.set("hash1", result1)
        assert cache.get("hash1").summary == "Original summary"
        cache.set("hash1", result2)
        assert cache.get("hash1").summary == "Updated summary"
        assert cache.size() == 1  # Still only one entry

    def test_cache_set_raises_on_invalid_hash(self, cache, sample_result):
        """Set should raise ValueError on invalid content_hash."""
        with pytest.raises(ValueError):
            cache.set("", sample_result)
        with pytest.raises(ValueError):
            cache.set(None, sample_result)  # type: ignore

    def test_cache_set_raises_on_invalid_result(self, cache):
        """Set should raise ValueError on invalid result."""
        with pytest.raises(ValueError):
            cache.set("hash1", "not a result")  # type: ignore

    def test_cache_get_with_invalid_hash_returns_none(self, cache):
        """Get with invalid hash should return None."""
        assert cache.get("") is None
        assert cache.get(None) is None  # type: ignore

    def test_cache_exists_with_invalid_hash_returns_false(self, cache):
        """Exists with invalid hash should return False."""
        assert cache.exists("") is False
        assert cache.exists(None) is False  # type: ignore

    def test_cache_clear_removes_all_entries(self, cache, sample_result):
        """Clear should remove all cached entries."""
        cache.set(sample_result.content_hash, sample_result)
        assert cache.size() == 1
        cache.clear()
        assert cache.size() == 0
        assert cache.get(sample_result.content_hash) is None

    def test_cache_enriched_at_set_automatically(self, cache):
        """If enriched_at is None, set() should populate it."""
        result = EnrichmentResult(
            content_hash="hash1",
            summary="Test",
            enriched_at=None,
        )
        before = datetime.now(timezone.utc)
        cache.set("hash1", result)
        after = datetime.now(timezone.utc)

        retrieved = cache.get("hash1")
        assert retrieved.enriched_at is not None
        # Parse ISO timestamp and verify it's within the test window
        enriched_dt = datetime.fromisoformat(retrieved.enriched_at)
        assert before <= enriched_dt <= after

    def test_cache_preserves_enriched_at_if_set(self, cache):
        """If enriched_at is provided, set() should preserve it."""
        original_time = "2026-05-31T12:00:00+00:00"
        result = EnrichmentResult(
            content_hash="hash1",
            summary="Test",
            enriched_at=original_time,
        )
        cache.set("hash1", result)
        retrieved = cache.get("hash1")
        assert retrieved.enriched_at == original_time


class TestCrossDocumentDeduplication:
    """Test cross-document chunk deduplication via content hash."""

    @pytest.fixture
    def cache(self):
        """Create a fresh cache for each test."""
        return EnrichmentCache()

    def test_identical_chunks_from_different_documents_share_cache(self, cache):
        """Identical chunk text from different documents should reuse cache."""
        # Simulate two documents with identical chunk text
        shared_text = "This is shared content across documents"
        shared_hash = compute_content_hash(shared_text)

        # First document: chunk enriched
        result1 = EnrichmentResult(
            content_hash=shared_hash,
            summary="Shared content summary",
            topics=["shared", "topic"],
            entities=["Entity1"],
        )
        cache.set(shared_hash, result1)

        # Second document: retrieve cached enrichment without re-enriching
        cached = cache.get(shared_hash)
        assert cached is not None
        assert cached.summary == "Shared content summary"
        assert cached.topics == ["shared", "topic"]

    def test_different_chunks_from_same_document_have_different_hashes(
        self, cache
    ):
        """Different chunks in same document should have different hashes."""
        chunk1_text = "First chunk content"
        chunk2_text = "Second chunk content"

        hash1 = compute_content_hash(chunk1_text)
        hash2 = compute_content_hash(chunk2_text)

        assert hash1 != hash2

        result1 = EnrichmentResult(
            content_hash=hash1,
            summary="First summary",
        )
        result2 = EnrichmentResult(
            content_hash=hash2,
            summary="Second summary",
        )

        cache.set(hash1, result1)
        cache.set(hash2, result2)

        assert cache.get(hash1).summary == "First summary"
        assert cache.get(hash2).summary == "Second summary"
        assert cache.size() == 2

    def test_similar_but_different_chunks_not_deduplicated(self, cache):
        """Similar but different text should have different hashes and not share cache."""
        text1 = "The quick brown fox jumps over the lazy dog"
        text2 = "The quick brown fox jumps over the lazy cat"

        hash1 = compute_content_hash(text1)
        hash2 = compute_content_hash(text2)
        assert hash1 != hash2

        result1 = EnrichmentResult(
            content_hash=hash1,
            summary="About a dog",
        )
        cache.set(hash1, result1)

        # hash2 should not be in cache
        assert cache.get(hash2) is None


class TestEnrichmentCacheSingleton:
    """Test singleton pattern for global cache instance."""

    def setup_method(self):
        """Reset cache singleton before each test."""
        reset_enrichment_cache()

    def teardown_method(self):
        """Clean up cache singleton after each test."""
        reset_enrichment_cache()

    def test_get_enrichment_cache_returns_same_instance(self):
        """Multiple calls to get_enrichment_cache should return same instance."""
        cache1 = get_enrichment_cache()
        cache2 = get_enrichment_cache()
        assert cache1 is cache2

    def test_get_enrichment_cache_initializes_on_first_call(self):
        """First call to get_enrichment_cache should create instance."""
        reset_enrichment_cache()
        cache = get_enrichment_cache()
        assert cache is not None
        assert isinstance(cache, EnrichmentCache)
        assert cache.size() == 0

    def test_reset_enrichment_cache_clears_singleton(self):
        """Reset should clear singleton and create fresh instance on next get."""
        cache1 = get_enrichment_cache()
        result = EnrichmentResult(
            content_hash="hash1",
            summary="Test",
        )
        cache1.set("hash1", result)
        assert cache1.size() == 1

        reset_enrichment_cache()
        cache2 = get_enrichment_cache()
        assert cache2.size() == 0

    def test_cache_persistence_across_operations(self):
        """Cache should maintain state across multiple operations."""
        cache = get_enrichment_cache()

        # Add multiple entries
        for i in range(5):
            result = EnrichmentResult(
                content_hash=f"hash{i}",
                summary=f"Summary {i}",
            )
            cache.set(f"hash{i}", result)

        # Verify all entries still exist
        assert cache.size() == 5
        for i in range(5):
            assert cache.exists(f"hash{i}")
            assert cache.get(f"hash{i}").summary == f"Summary {i}"


class TestEnrichmentCacheMetrics:
    """Test cache metrics and reporting."""

    @pytest.fixture
    def cache(self):
        """Create a fresh cache for each test."""
        return EnrichmentCache()

    def test_cache_size_increments(self, cache):
        """Cache size should increment with each set operation."""
        assert cache.size() == 0
        result = EnrichmentResult(
            content_hash="hash1",
            summary="Test",
        )
        cache.set("hash1", result)
        assert cache.size() == 1
        cache.set("hash2", result)
        assert cache.size() == 2

    def test_cache_size_no_increment_on_overwrite(self, cache):
        """Overwriting same hash should not increment size."""
        result1 = EnrichmentResult(
            content_hash="hash1",
            summary="Original",
        )
        result2 = EnrichmentResult(
            content_hash="hash1",
            summary="Updated",
        )
        cache.set("hash1", result1)
        assert cache.size() == 1
        cache.set("hash1", result2)
        assert cache.size() == 1

    def test_cache_stats_returns_dict_with_size(self, cache):
        """Stats should return dict with size key."""
        result = EnrichmentResult(
            content_hash="hash1",
            summary="Test",
        )
        cache.set("hash1", result)
        stats = cache.stats()
        assert isinstance(stats, dict)
        assert "size" in stats
        assert stats["size"] == 1
