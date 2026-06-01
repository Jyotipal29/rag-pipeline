"""Standard response models."""

from typing import Any

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    code: str
    details: dict[str, Any] | None = None


class SuccessResponse(BaseModel):
    """Standard success response."""

    data: dict[str, Any] | None = None
    message: str | None = None


class PaginatedResponse(BaseModel):
    """Paginated response."""

    data: list[dict[str, Any]]
    total: int
    skip: int
    limit: int
    has_more: bool
