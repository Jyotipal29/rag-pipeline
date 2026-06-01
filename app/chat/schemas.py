"""Chat request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class ChatMessageRequest(BaseModel):
    """Chat message request."""

    query: str = Field(..., min_length=1)


class ChatSourceChunk(BaseModel):
    """Source chunk in chat response."""

    page: int
    preview: str
    score: float


class ChatMessageResponse(BaseModel):
    """Single chat message."""

    role: str  # "user" or "assistant"
    content: str
    source_chunks: list[ChatSourceChunk] | None = None
    query_type: str | None = None
    created_at: datetime | None = None


class ChatHistoryResponse(BaseModel):
    """Chat history with pagination."""

    messages: list[ChatMessageResponse]
    total: int
    has_more: bool
