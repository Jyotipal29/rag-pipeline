"""MongoDB connection and utilities using Motor (async driver)."""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config.settings import get_settings

_db_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def get_db() -> AsyncIOMotorDatabase:
    """Get MongoDB database instance."""
    global _db
    if _db is None:
        await connect_db()
    return _db


async def connect_db() -> None:
    """Initialize MongoDB connection."""
    global _db_client, _db
    settings = get_settings()
    _db_client = AsyncClient(settings.mongodb_url)
    _db = _db_client[settings.mongodb_db_name]
    # Test connection
    try:
        await _db.command("ping")
        print("✅ MongoDB connected")
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        raise


async def close_db() -> None:
    """Close MongoDB connection."""
    global _db_client
    if _db_client:
        _db_client.close()
        print("MongoDB disconnected")
