"""Authentication service for user registration, login, and profile management."""

import secrets
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from motor.motor_asyncio import AsyncDatabase

from app.auth.schemas import UserSchema
from app.auth.utils import hash_password, hash_refresh_token, verify_password
from app.db.collections import USERS_COLLECTION
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def register_user(
    db: AsyncDatabase, email: str, password: str, name: str, auth_provider: str = "email"
) -> dict:
    """Register a new user."""
    users_col = db[USERS_COLLECTION]

    # Check if user already exists
    existing = await users_col.find_one({"email": email})
    if existing:
        raise ValueError(f"User with email {email} already registered")

    # Create verification token
    verification_token = secrets.token_urlsafe(32)
    verification_expires = datetime.now(timezone.utc) + timedelta(hours=24)

    user_data = {
        "email": email,
        "password_hash": hash_password(password),
        "name": name,
        "auth_provider": auth_provider,
        "is_verified": False,
        "verification_token": verification_token,
        "verification_token_expires": verification_expires,
        "google_id": None,
        "refresh_token_hash": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    result = await users_col.insert_one(user_data)
    user_data["_id"] = result.inserted_id

    logger.info(f"User registered: {email}")
    return user_data


async def get_user_by_email(db: AsyncDatabase, email: str) -> dict | None:
    """Get user by email."""
    users_col = db[USERS_COLLECTION]
    return await users_col.find_one({"email": email})


async def get_user_by_id(db: AsyncDatabase, user_id: str) -> dict | None:
    """Get user by ID."""
    users_col = db[USERS_COLLECTION]
    try:
        return await users_col.find_one({"_id": ObjectId(user_id)})
    except Exception:
        return None


async def get_user_by_google_id(db: AsyncDatabase, google_id: str) -> dict | None:
    """Get user by Google ID."""
    users_col = db[USERS_COLLECTION]
    return await users_col.find_one({"google_id": google_id})


async def verify_user_password(db: AsyncDatabase, email: str, password: str) -> dict | None:
    """Verify user password and return user if valid."""
    user = await get_user_by_email(db, email)
    if not user or not user.get("password_hash"):
        return None

    if not verify_password(password, user["password_hash"]):
        return None

    if not user.get("is_verified"):
        raise ValueError("Email not verified")

    return user


async def verify_email(db: AsyncDatabase, token: str) -> bool:
    """Verify email with token and mark user as verified."""
    users_col = db[USERS_COLLECTION]

    user = await users_col.find_one({
        "verification_token": token,
        "verification_token_expires": {"$gt": datetime.now(timezone.utc)},
    })

    if not user:
        return False

    await users_col.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "is_verified": True,
                "verification_token": None,
                "verification_token_expires": None,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )

    logger.info(f"Email verified for user: {user['email']}")
    return True


async def create_or_update_google_user(db: AsyncDatabase, google_id: str, email: str, name: str) -> dict:
    """Create or update user authenticated via Google OAuth."""
    users_col = db[USERS_COLLECTION]

    existing = await users_col.find_one({"google_id": google_id})
    if existing:
        logger.info(f"Google user login: {email}")
        return existing

    # Check if email already registered
    email_exists = await users_col.find_one({"email": email})
    if email_exists:
        # Link Google ID to existing user
        await users_col.update_one(
            {"_id": email_exists["_id"]},
            {
                "$set": {
                    "google_id": google_id,
                    "auth_provider": "google",
                    "is_verified": True,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        logger.info(f"Google ID linked to existing user: {email}")
        return await get_user_by_id(db, str(email_exists["_id"]))

    # Create new user
    user_data = {
        "email": email,
        "password_hash": None,
        "name": name,
        "auth_provider": "google",
        "google_id": google_id,
        "is_verified": True,
        "verification_token": None,
        "verification_token_expires": None,
        "refresh_token_hash": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    result = await users_col.insert_one(user_data)
    user_data["_id"] = result.inserted_id

    logger.info(f"Google user created: {email}")
    return user_data


async def update_refresh_token_hash(db: AsyncDatabase, user_id: str, token_hash: str) -> None:
    """Store hashed refresh token in user document."""
    users_col = db[USERS_COLLECTION]
    await users_col.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "refresh_token_hash": token_hash,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )


async def invalidate_refresh_token(db: AsyncDatabase, user_id: str) -> None:
    """Clear the stored refresh token hash (logout)."""
    users_col = db[USERS_COLLECTION]
    await users_col.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"refresh_token_hash": None}},
    )


async def set_password_reset_token(db: AsyncDatabase, email: str) -> str:
    """Generate and store password reset token."""
    users_col = db[USERS_COLLECTION]

    user = await get_user_by_email(db, email)
    if not user:
        # Don't reveal if email exists (security best practice)
        return None

    reset_token = secrets.token_urlsafe(32)
    reset_expires = datetime.now(timezone.utc) + timedelta(hours=1)

    await users_col.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "reset_token": reset_token,
                "reset_token_expires": reset_expires,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )

    logger.info(f"Password reset token generated for: {email}")
    return reset_token


async def reset_password(db: AsyncDatabase, token: str, new_password: str) -> bool:
    """Reset user password with token."""
    users_col = db[USERS_COLLECTION]

    user = await users_col.find_one({
        "reset_token": token,
        "reset_token_expires": {"$gt": datetime.now(timezone.utc)},
    })

    if not user:
        return False

    await users_col.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "password_hash": hash_password(new_password),
                "reset_token": None,
                "reset_token_expires": None,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )

    logger.info(f"Password reset for user: {user['email']}")
    return True
