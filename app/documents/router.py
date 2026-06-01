"""Document management routes."""

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.auth.dependencies import get_current_user
from app.auth.service import get_user_by_id
from app.config.settings import get_settings
from app.db.mongo import get_db
from app.documents import service
from app.documents.schemas import DocumentDetailResponse, DocumentListResponse, DocumentStatusResponse, DocumentUploadResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


def _doc_to_detail(doc: dict) -> DocumentDetailResponse:
    """Convert document to detail response."""
    return DocumentDetailResponse(
        id=str(doc["_id"]),
        filename=doc["filename"],
        status=doc["status"],
        page_count=doc.get("page_count"),
        chunk_count=doc.get("chunk_count"),
        summary=doc.get("summary"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Upload a PDF document for processing."""
    settings = get_settings()

    # Validate file type
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are allowed")

    # Validate file size
    file_content = await file.read()
    file_size = len(file_content)
    if file_size > settings.max_pdf_size_mb * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File too large")

    try:
        import magic
        mime = magic.Magic(mime=True)
        detected_type = mime.from_buffer(file_content)
        if "pdf" not in detected_type.lower():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid PDF file")
    except Exception as e:
        logger.warning(f"MIME detection failed (continuing): {e}")

    # Create document record
    user_id = str(current_user["_id"])
    doc_id = await service.create_document(db, user_id, file.filename, file_size)

    # Save file
    upload_dir = settings.upload_dir
    user_upload_dir = f"{upload_dir}/{user_id}"
    import os
    os.makedirs(user_upload_dir, exist_ok=True)

    file_path = f"{user_upload_dir}/{doc_id}.pdf"
    with open(file_path, "wb") as f:
        f.write(file_content)

    # Update storage path
    await db.documents.update_one(
        {"_id": ObjectId(doc_id)},
        {"$set": {"storage_path": file_path}}
    )

    # Enqueue background processing
    background_tasks.add_task(
        _process_document,
        doc_id=doc_id,
        user_id=user_id,
        file_path=file_path,
        db=db,
    )

    return DocumentUploadResponse(
        doc_id=doc_id,
        status="processing",
        message="Document upload started. Check status endpoint for progress.",
    )


async def _process_document(doc_id: str, user_id: str, file_path: str, db: AsyncIOMotorDatabase) -> None:
    """Background task to process uploaded document."""
    try:
        from app.documents.pipeline_adapter import run_pipeline

        await run_pipeline(doc_id, user_id, file_path, db)
    except Exception as e:
        logger.error(f"Document processing failed for {doc_id}: {e}")
        await service.update_document_status(db, doc_id, "error", error_msg=str(e))


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    skip: int = 0,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """List current user's documents."""
    user_id = str(current_user["_id"])
    documents, total = await service.list_documents(db, user_id, skip, limit)

    return DocumentListResponse(
        documents=[_doc_to_detail(doc) for doc in documents],
        total=total,
    )


@router.get("/{doc_id}", response_model=DocumentDetailResponse)
async def get_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Get document details."""
    user_id = str(current_user["_id"])
    doc = await service.get_document(db, user_id, doc_id)

    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return _doc_to_detail(doc)


@router.get("/{doc_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Get document processing status."""
    user_id = str(current_user["_id"])
    doc = await service.get_document(db, user_id, doc_id)

    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    progress = {
        "processing": 50,
        "ready": 100,
        "error": 0,
    }.get(doc["status"], 0)

    return DocumentStatusResponse(
        doc_id=doc_id,
        status=doc["status"],
        progress=progress,
        error_message=doc.get("error_message"),
        chunk_count=doc.get("chunk_count"),
        summary=doc.get("summary"),
        page_count=doc.get("page_count"),
    )


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Delete a document."""
    user_id = str(current_user["_id"])
    success = await service.delete_document(db, user_id, doc_id)

    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")


from bson import ObjectId
