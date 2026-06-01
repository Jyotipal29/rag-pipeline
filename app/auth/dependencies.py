"""FastAPI dependencies for JWT authentication."""

from fastapi import Depends, HTTPException, status
from motor.motor_asyncio import AsyncDatabase

from app.auth.utils import verify_access_token
from app.auth.service import get_user_by_id
from app.db.mongo import get_db
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def get_token_from_header(authorization: str | None = None) -> str:
    """Extract Bearer token from Authorization header."""
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization header")

    return parts[1]


async def get_current_user(
    authorization: str | None = None,
    db: AsyncDatabase = Depends(get_db),
) -> dict:
    """
    FastAPI dependency to get the current authenticated user.

    Raises:
        HTTPException: 401 if token is invalid or user not found
    """
    token = await get_token_from_header(authorization)

    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


async def optional_user(
    authorization: str | None = None,
    db: AsyncDatabase = Depends(get_db),
) -> dict | None:
    """
    FastAPI dependency to optionally get the current authenticated user.

    Returns None if no valid token is provided, instead of raising an error.
    """
    if not authorization:
        return None

    try:
        return await get_current_user(authorization=authorization, db=db)
    except HTTPException:
        return None
