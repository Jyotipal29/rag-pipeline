"""Document management service."""

from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId
from motor.motor_asyncio import AsyncDatabase

from app.config.settings import get_settings
from app.db.collections import DOCUMENTS_COLLECTION
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def create_document(db: AsyncDatabase, user_id: str, filename: str, file_size: int) -> str:
    """Create a new document record."""
    docs_col = db[DOCUMENTS_COLLECTION]

    doc_data = {
        "user_id": ObjectId(user_id),
        "filename": filename,
        "file_size_bytes": file_size,
        "storage_path": None,
        "page_count": None,
        "chunk_count": None,
        "status": "processing",
        "error_message": None,
        "summary": None,
        "qdrant_collection": "user_documents",
        "qdrant_doc_id": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    result = await docs_col.insert_one(doc_data)
    return str(result.inserted_id)


async def get_document(db: AsyncDatabase, user_id: str, doc_id: str) -> dict | None:
    """Get document by ID (verify user ownership)."""
    docs_col = db[DOCUMENTS_COLLECTION]
    try:
        return await docs_col.find_one({
            "_id": ObjectId(doc_id),
            "user_id": ObjectId(user_id)
        })
    except Exception:
        return None


async def list_documents(db: AsyncDatabase, user_id: str, skip: int = 0, limit: int = 20) -> tuple[list[dict], int]:
    """List user's documents."""
    docs_col = db[DOCUMENTS_COLLECTION]

    total = await docs_col.count_documents({"user_id": ObjectId(user_id)})
    documents = await docs_col.find({
        "user_id": ObjectId(user_id)
    }).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)

    return documents, total


async def delete_document(db: AsyncDatabase, user_id: str, doc_id: str) -> bool:
    """Delete document and associated data."""
    docs_col = db[DOCUMENTS_COLLECTION]

    doc = await get_document(db, user_id, doc_id)
    if not doc:
        return False

    # Delete file from disk
    if doc.get("storage_path"):
        try:
            Path(doc["storage_path"]).unlink()
        except Exception as e:
            logger.warning(f"Failed to delete file {doc['storage_path']}: {e}")

    # Delete document record
    await docs_col.delete_one({"_id": ObjectId(doc_id)})

    # Delete from Qdrant (vectorstore) if indexed
    if doc.get("qdrant_doc_id"):
        try:
            from app.vectorstore.qdrant_client import delete_by_document
            await delete_by_document(doc["qdrant_doc_id"], collection="user_documents")
        except Exception as e:
            logger.warning(f"Failed to delete from Qdrant: {e}")

    # Delete chat messages
    from app.db.collections import CHAT_MESSAGES_COLLECTION
    await db[CHAT_MESSAGES_COLLECTION].delete_many({
        "user_id": ObjectId(user_id),
        "doc_id": doc_id
    })

    return True


async def update_document_status(
    db: AsyncDatabase,
    doc_id: str,
    status: str,
    error_msg: str | None = None,
    summary: str | None = None,
    chunk_count: int | None = None,
    page_count: int | None = None,
    qdrant_doc_id: str | None = None,
) -> None:
    """Update document status and metadata."""
    docs_col = db[DOCUMENTS_COLLECTION]

    update_data = {
        "status": status,
        "updated_at": datetime.now(timezone.utc),
    }

    if error_msg is not None:
        update_data["error_message"] = error_msg
    if summary is not None:
        update_data["summary"] = summary
    if chunk_count is not None:
        update_data["chunk_count"] = chunk_count
    if page_count is not None:
        update_data["page_count"] = page_count
    if qdrant_doc_id is not None:
        update_data["qdrant_doc_id"] = qdrant_doc_id

    await docs_col.update_one(
        {"_id": ObjectId(doc_id)},
        {"$set": update_data}
    )

    logger.info(f"Document {doc_id} status updated to {status}")
