"""Bridge between document management and existing RAG pipeline with user_id injection."""

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.documents import service as doc_service
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def run_pipeline(doc_id: str, user_id: str, file_path: str, db: AsyncIOMotorDatabase) -> None:
    """
    Run the document processing pipeline with user_id metadata injection.

    This wraps the existing RAG pipeline and ensures user_id is stored in Qdrant payloads.
    """
    try:
        await doc_service.update_document_status(db, doc_id, "processing")

        # Step 1: Extract PDF using existing ingestion pipeline
        logger.info(f"Extracting PDF: {file_path}")
        from app.ingestion.pdf_extractor import extract_pdf

        extracted = await extract_pdf(file_path)
        logger.info(f"PDF extracted: {len(extracted.pages)} pages")

        # Update document with page count
        await doc_service.update_document_status(db, doc_id, "processing", page_count=len(extracted.pages))

        # Step 2: Chunk and index with user_id metadata
        logger.info(f"Chunking and indexing document")
        from app.indexing.main import index_document

        # Pass user_id and doc_id as metadata so chunks get stored in Qdrant with these fields
        extra_metadata = {
            "user_id": user_id,
            "doc_type": "user_doc",
        }

        # Index returns result with chunk_count
        result = await index_document(
            document_id=doc_id,
            extracted_data=extracted,
            extra_metadata=extra_metadata,
            collection_name="user_documents",
        )

        logger.info(f"Document indexed: {result.chunk_count} chunks")

        # Step 3: Generate summary (optional - use existing pipeline if available)
        summary = f"Document with {result.chunk_count} chunks from {len(extracted.pages)} pages"

        # Step 4: Mark document as ready
        await doc_service.update_document_status(
            db,
            doc_id,
            "ready",
            summary=summary,
            chunk_count=result.chunk_count,
            qdrant_doc_id=doc_id,  # The document_id used in Qdrant
        )

        logger.info(f"Document processing complete: {doc_id}")

    except Exception as e:
        logger.error(f"Document processing failed for {doc_id}: {e}", exc_info=True)
        await doc_service.update_document_status(db, doc_id, "error", error_msg=str(e))
        raise
