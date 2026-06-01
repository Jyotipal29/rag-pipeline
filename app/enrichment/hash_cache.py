"""
Content hash caching layer for enrichment deduplication (U2).

Provides:
- EnrichmentCache: Stores enrichment results indexed by content hash
- Deterministic content hashing for cross-document deduplication
- In-memory cache with optional Qdrant persistence

The cache enables reuse of enrichment work when identical chunk text
appears across different documents.

Cache Key: SHA256(normalized text only)
  - Normalization: lowercase, strip, collapse whitespace
  - Cross-document dedup enabled (same text = same enrichment)

Cache Value: EnrichmentResult
  - summary: LLM-generated 1-sentence description
  - topics: 3-8 semantic keywords
  - entities: Named entities (people, orgs, dates, amounts)
  - enriched_at: ISO timestamp of enrichment completion
"""

from datetime import datetime, timezone

from app.models.enrichment import EnrichmentResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


class EnrichmentCache:
    """
    In-memory cache for enrichment results, keyed by content hash.

    Stores enrichment results (summary, topics, entities) indexed by SHA256 hash
    of normalized chunk text. Enables cross-document deduplication when identical
    chunks appear in different documents.

    Design:
    - Key: content_hash (str, 64 chars, SHA256 hex)
    - Value: EnrichmentResult (Pydantic model)
    - Storage: In-memory dict (Python 3.11+, thread-safe for read-heavy workloads)
    - Persistence: Optional Qdrant updates (deferred to background tasks)

    Thread safety:
    - Designed for single-threaded access (FastAPI + Celery workers run in separate processes)
    - For multi-threaded access, wrap with threading.Lock
    """

    def __init__(self) -> None:
        """Initialize empty cache."""
        self._cache: dict[str, EnrichmentResult] = {}
        logger.info("Initialized enrichment cache")

    def get(self, content_hash: str) -> EnrichmentResult | None:
        """
        Retrieve cached enrichment result by content hash.

        Args:
            content_hash: SHA256 hash of normalized chunk text (64-char hex string)

        Returns:
            EnrichmentResult if cache hit; None if miss or invalid hash
        """
        if not content_hash or not isinstance(content_hash, str):
            return None

        result = self._cache.get(content_hash)
        if result:
            logger.debug(
                "Cache hit for hash=%s (summary=%d chars)",
                content_hash[:8],
                len(result.summary),
            )
        return result

    def set(self, content_hash: str, result: EnrichmentResult) -> None:
        """
        Store enrichment result in cache.

        Args:
            content_hash: SHA256 hash of normalized chunk text
            result: EnrichmentResult to cache

        Raises:
            ValueError: If content_hash is empty or result is invalid
        """
        if not content_hash or not isinstance(content_hash, str):
            raise ValueError("content_hash must be a non-empty string")
        if not isinstance(result, EnrichmentResult):
            raise ValueError("result must be an EnrichmentResult instance")

        # Ensure enriched_at is set to current time if not provided
        if result.enriched_at is None:
            result.enriched_at = datetime.now(timezone.utc).isoformat()

        self._cache[content_hash] = result
        logger.debug(
            "Cache set for hash=%s (summary=%d chars, topics=%d)",
            content_hash[:8],
            len(result.summary),
            len(result.topics),
        )

    def exists(self, content_hash: str) -> bool:
        """
        Check if content_hash is in cache.

        Args:
            content_hash: SHA256 hash of normalized chunk text

        Returns:
            True if hash is in cache; False otherwise
        """
        if not content_hash or not isinstance(content_hash, str):
            return False
        return content_hash in self._cache

    def size(self) -> int:
        """
        Return current cache size (number of cached hashes).

        Returns:
            Number of entries in cache
        """
        return len(self._cache)

    def clear(self) -> None:
        """Clear all cached entries. Used for testing and cache reset."""
        self._cache.clear()
        logger.info("Enrichment cache cleared")

    def stats(self) -> dict[str, int]:
        """
        Return cache statistics.

        Returns:
            Dict with 'size' key containing number of cached entries
        """
        return {"size": self.size()}


# Global cache instance (singleton)
_cache_instance: EnrichmentCache | None = None


def get_enrichment_cache() -> EnrichmentCache:
    """
    Get or create global enrichment cache instance.

    Uses singleton pattern: first call creates cache, subsequent calls
    return same instance. Safe for module imports across the application.

    Returns:
        EnrichmentCache singleton instance
    """
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = EnrichmentCache()
    return _cache_instance


def reset_enrichment_cache() -> None:
    """
    Reset global cache instance. Used for testing only.

    Clears all cached entries and resets singleton.
    """
    global _cache_instance
    if _cache_instance is not None:
        _cache_instance.clear()
    _cache_instance = None
    logger.info("Reset enrichment cache singleton")
