from datetime import datetime, timezone

from pydantic import BaseModel, Field


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


class IndexingResult(BaseModel):
    document_id: str
    filename: str
    page_count: int
    chunk_count: int
    indexed_count: int
    ingestion: IngestionResult


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


class SearchResult(BaseModel):
    query: str
    hits: list[SearchHit]
