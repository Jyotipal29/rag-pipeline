"""Pydantic request/response models for authentication."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """User registration request."""

    email: EmailStr
    password: str = Field(..., min_length=8)
    name: str = Field(..., min_length=1, max_length=255)


class LoginRequest(BaseModel):
    """User login request."""

    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """Token refresh request."""

    refresh_token: str


class TokenPayload(BaseModel):
    """JWT token payload."""

    sub: str
    email: str
    type: str  # "access" or "refresh"
    exp: int


class UserSchema(BaseModel):
    """User data model."""

    id: str = Field(..., alias="_id")
    email: str
    name: str
    auth_provider: str
    is_verified: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True


class LoginResponse(BaseModel):
    """Login response with tokens."""

    access_token: str
    refresh_token: str | None = None
    user: UserSchema


class RegisterResponse(BaseModel):
    """Registration response."""

    user: UserSchema
    message: str


class TokenRefreshResponse(BaseModel):
    """Token refresh response."""

    access_token: str
    refresh_token: str


class VerifyEmailRequest(BaseModel):
    """Email verification request."""

    token: str


class ForgotPasswordRequest(BaseModel):
    """Forgot password request."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Password reset request."""

    token: str
    new_password: str = Field(..., min_length=8)


class GoogleAuthResponse(BaseModel):
    """Google auth endpoint response."""

    auth_url: str


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    code: str
    details: dict[str, Any] | None = None
