"""Document request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class DocumentUploadResponse(BaseModel):
    """Document upload response."""

    doc_id: str
    status: str
    message: str


class DocumentDetailResponse(BaseModel):
    """Document detail response."""

    id: str
    filename: str
    status: str
    page_count: int | None = None
    chunk_count: int | None = None
    summary: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    """Document list response."""

    documents: list[DocumentDetailResponse]
    total: int


class DocumentStatusResponse(BaseModel):
    """Document status response for polling."""

    doc_id: str
    status: str
    progress: int = 0
    error_message: str | None = None
    chunk_count: int | None = None
    summary: str | None = None
    page_count: int | None = None
