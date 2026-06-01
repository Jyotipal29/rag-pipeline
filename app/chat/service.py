"""Chat service for Q&A and message management."""

from datetime import datetime, timezone

from bson import ObjectId
from motor.motor_asyncio import AsyncDatabase

from app.db.collections import CHAT_MESSAGES_COLLECTION, DOCUMENTS_COLLECTION
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def verify_doc_access(db: AsyncDatabase, user_id: str, doc_id: str) -> dict | None:
    """Verify user has access to document."""
    docs_col = db[DOCUMENTS_COLLECTION]
    try:
        return await docs_col.find_one({
            "_id": ObjectId(doc_id),
            "user_id": ObjectId(user_id)
        })
    except Exception:
        return None


async def save_user_message(
    db: AsyncDatabase, user_id: str, doc_id: str, doc_type: str, content: str
) -> str:
    """Save user message to chat history."""
    messages_col = db[CHAT_MESSAGES_COLLECTION]

    msg_data = {
        "user_id": ObjectId(user_id),
        "doc_id": doc_id,
        "doc_type": doc_type,
        "role": "user",
        "content": content,
        "source_chunks": None,
        "query_type": None,
        "created_at": datetime.now(timezone.utc),
    }

    result = await messages_col.insert_one(msg_data)
    return str(result.inserted_id)


async def save_assistant_message(
    db: AsyncDatabase,
    user_id: str,
    doc_id: str,
    doc_type: str,
    content: str,
    source_chunks: list[dict] | None = None,
    query_type: str | None = None,
) -> str:
    """Save assistant message to chat history."""
    messages_col = db[CHAT_MESSAGES_COLLECTION]

    msg_data = {
        "user_id": ObjectId(user_id),
        "doc_id": doc_id,
        "doc_type": doc_type,
        "role": "assistant",
        "content": content,
        "source_chunks": source_chunks or [],
        "query_type": query_type,
        "created_at": datetime.now(timezone.utc),
    }

    result = await messages_col.insert_one(msg_data)
    return str(result.inserted_id)


async def get_chat_history(
    db: AsyncDatabase, user_id: str, doc_id: str, skip: int = 0, limit: int = 20
) -> tuple[list[dict], int]:
    """Get chat history for a document."""
    messages_col = db[CHAT_MESSAGES_COLLECTION]

    total = await messages_col.count_documents({
        "user_id": ObjectId(user_id),
        "doc_id": doc_id
    })

    messages = await messages_col.find({
        "user_id": ObjectId(user_id),
        "doc_id": doc_id
    }).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)

    return messages, total


async def delete_chat_history(db: AsyncDatabase, user_id: str, doc_id: str) -> None:
    """Delete all chat messages for a document."""
    messages_col = db[CHAT_MESSAGES_COLLECTION]
    await messages_col.delete_many({
        "user_id": ObjectId(user_id),
        "doc_id": doc_id
    })

    logger.info(f"Chat history deleted for user {user_id}, doc {doc_id}")


def format_history_for_rag(messages: list[dict]) -> list[dict]:
    """Format MongoDB chat messages for RAG pipeline."""
    formatted = []
    for msg in messages:
        formatted.append({
            "role": msg["role"],
            "content": msg["content"]
        })
    # Reverse to chronological order (MongoDB returns newest first)
    return list(reversed(formatted))
