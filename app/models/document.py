from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enrichment import EnrichmentStatus


class Page(BaseModel):
    page_number: int = Field(..., ge=1, description="1-based page index")
    text: str
    char_count: int = Field(..., ge=0)


class IngestionResult(BaseModel):
    document_id: str
    filename: str
    page_count: int
    pages: list[Page]
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_path: str
    processed_path: str


class Chunk(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    page_number: int = Field(..., ge=1)
    chunk_index: int = Field(..., ge=0)
    text: str
    char_start: int = Field(..., ge=0)
    char_end: int = Field(..., ge=0)
    token_count: int = Field(..., ge=0)
    # Phase 3B — enrichment
    summary: str = ""
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    embedding_text: str = ""
    # U1 — enrichment status tracking
    enrichment_status: EnrichmentStatus = Field(
        default=EnrichmentStatus.PENDING,
        description="Current enrichment status: PENDING, PROCESSING, COMPLETED, or FAILED",
    )
    content_hash: str = Field(
        default="",
        description="SHA256 hash of normalized chunk text for cross-document deduplication",
    )
    enriched_at: datetime | None = Field(
        default=None, description="UTC timestamp when enrichment completed"
    )
    # Phase 3C — structure
    section_id: str = ""
    section_title: str = ""
    parent_chunk_id: str = ""
    parent_text: str = ""
    chunk_role: Literal["child", "parent"] = "child"

    def searchable_text(self) -> str:
        """Text used for BM25 (raw + semantic keywords)."""
        parts = [self.text]
        if self.topics:
            parts.append(" ".join(self.topics))
        if self.summary:
            parts.append(self.summary)
        return "\n".join(parts)

    def text_for_embedding(self) -> str:
        if self.embedding_text.strip():
            return self.embedding_text
        header = f"Document: {self.filename}\nPage: {self.page_number}"
        if self.section_title:
            header += f"\nSection: {self.section_title}"
        if self.summary:
            header += f"\nSummary: {self.summary}"
        if self.topics:
            header += f"\nTopics: {', '.join(self.topics)}"
        return f"{header}\n\n{self.text}"


class IndexingResult(BaseModel):
    document_id: str
    filename: str
    page_count: int
    chunk_count: int
    indexed_count: int
    ingestion: IngestionResult


class BatchIndexingResult(BaseModel):
    results: list[IndexingResult]
    document_ids: list[str]
    total_indexed: int
    total_chunks: int


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    page_number: int
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    score: float
    parent_chunk_id: str = ""
    section_title: str = ""
    parent_text: str = ""


class SearchResult(BaseModel):
    query: str
    hits: list[SearchHit]


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    page_number: int
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    score: float
    retrieval_source: str = "dense"
    parent_chunk_id: str = ""
    section_title: str = ""
    parent_text: str = ""


class Citation(BaseModel):
    citation_id: int
    document_id: str
    filename: str
    page_number: int
    chunk_id: str
    quote: str


class AskRequest(BaseModel):
    question: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    document_ids: list[str] = Field(
        default_factory=list,
        description="When set, retrieval is limited to these document IDs",
    )


class AskResponse(BaseModel):
    question: str
    answer: str
    citations: list[Citation]
    retrieved_chunks: list[RetrievedChunk]
    rewritten_query: str | None = None
    query_type: str | None = None
    retrieval_queries: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    coverage_complete: bool | None = None
    validation_warnings: list[str] = Field(default_factory=list)
