"""JWT and cryptography utilities for authentication."""

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config.settings import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(password, hashed)


def create_access_token(user_id: str, email: str, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    settings = get_settings()
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_access_expire_minutes)

    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {
        "sub": user_id,
        "email": email,
        "type": "access",
        "exp": expire,
    }
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm="HS256")
    return encoded_jwt


def create_refresh_token(user_id: str, expires_delta: timedelta | None = None) -> str:
    """Create a JWT refresh token."""
    settings = get_settings()
    if expires_delta is None:
        expires_delta = timedelta(days=settings.jwt_refresh_expire_days)

    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {
        "sub": user_id,
        "type": "refresh",
        "exp": expire,
    }
    encoded_jwt = jwt.encode(to_encode, settings.jwt_refresh_secret, algorithm="HS256")
    return encoded_jwt


def verify_access_token(token: str) -> dict[str, Any] | None:
    """Verify and decode an access token."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


def verify_refresh_token(token: str) -> dict[str, Any] | None:
    """Verify and decode a refresh token."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_refresh_secret, algorithms=["HS256"])
        if payload.get("type") != "refresh":
            return None
        return payload
    except JWTError:
        return None


def hash_refresh_token(token: str) -> str:
    """Hash a refresh token for storage in MongoDB."""
    return pwd_context.hash(token)


def verify_refresh_token_hash(token: str, hashed: str) -> bool:
    """Verify a refresh token against its hash."""
    return pwd_context.verify(token, hashed)
