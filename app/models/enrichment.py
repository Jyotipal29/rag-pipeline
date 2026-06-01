"""
Enrichment status tracking and models (U1).

Provides:
- EnrichmentStatus enum for status tracking
- Content hash computation for cross-document deduplication
- Enrichment result schemas
"""
import hashlib
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class EnrichmentStatus(str, Enum):
    """Enrichment status for chunks and documents."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def compute_content_hash(text: str) -> str:
    """
    Compute SHA256 hash of normalized chunk text for deduplication.

    Normalization:
    - Lowercase
    - Strip leading/trailing whitespace
    - Collapse multiple whitespace into single space

    This ensures identical content across documents produces the same hash,
    enabling cross-document deduplication in the enrichment cache.

    Args:
        text: Raw chunk text

    Returns:
        Hex-encoded SHA256 digest (64 chars)
    """
    # Normalize: lowercase, strip, collapse whitespace
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()


class EnrichmentResult(BaseModel):
    """Result of enriching a chunk."""

    content_hash: str = Field(..., description="SHA256 hash of normalized text")
    summary: str = Field(..., description="LLM-generated chunk summary")
    topics: list[str] = Field(default_factory=list, description="Extracted topics")
    entities: list[str] = Field(default_factory=list, description="Extracted entities")
    enriched_at: Optional[str] = Field(
        default=None, description="ISO timestamp when enrichment completed"
    )


class EnrichmentRequest(BaseModel):
    """Request to enrich a chunk or batch of chunks."""

    chunk_id: str
    text: str
    content_hash: Optional[str] = None


class DocumentEnrichmentStatus(BaseModel):
    """Track enrichment progress for a document."""

    document_id: str
    total_chunks: int = Field(..., ge=0)
    pending_chunks: int = Field(..., ge=0)
    processing_chunks: int = Field(..., ge=0)
    completed_chunks: int = Field(..., ge=0)
    failed_chunks: int = Field(..., ge=0)

    @property
    def completion_percentage(self) -> float:
        """Calculate completion percentage."""
        if self.total_chunks == 0:
            return 0.0
        return round((self.completed_chunks / self.total_chunks) * 100, 2)

    @property
    def all_completed(self) -> bool:
        """Check if all chunks are enriched."""
        return self.completed_chunks == self.total_chunks

    @property
    def has_failures(self) -> bool:
        """Check if any chunks failed enrichment."""
        return self.failed_chunks > 0
