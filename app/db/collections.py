"""MongoDB collection names and index creation."""

from motor.motor_asyncio import AsyncIOMotorDatabase

USERS_COLLECTION = "users"
DOCUMENTS_COLLECTION = "documents"
CHAT_MESSAGES_COLLECTION = "chat_messages"
RESEARCH_PAPERS_COLLECTION = "research_papers"


async def create_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create MongoDB indexes on startup."""
    # Users collection indexes
    await db[USERS_COLLECTION].create_index("email", unique=True)
    await db[USERS_COLLECTION].create_index("google_id", sparse=True, unique=True)

    # Documents collection indexes
    await db[DOCUMENTS_COLLECTION].create_index("user_id")
    await db[DOCUMENTS_COLLECTION].create_index("status")
    await db[DOCUMENTS_COLLECTION].create_index("created_at")

    # Chat messages collection indexes
    await db[CHAT_MESSAGES_COLLECTION].create_index([("user_id", 1), ("doc_id", 1)])
    await db[CHAT_MESSAGES_COLLECTION].create_index("created_at")

    # Research papers collection indexes
    await db[RESEARCH_PAPERS_COLLECTION].create_index("topic_tags")
    await db[RESEARCH_PAPERS_COLLECTION].create_index("year")
    await db[RESEARCH_PAPERS_COLLECTION].create_index([("title", "text"), ("abstract", "text")])

    print("✅ MongoDB indexes created")
