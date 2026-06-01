"""Chat routes with SSE streaming."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncDatabase

from app.auth.dependencies import get_current_user
from app.chat import service
from app.chat.schemas import ChatHistoryResponse, ChatMessageRequest
from app.documents.service import get_document
from app.db.mongo import get_db
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/{doc_id}/message")
async def chat_message(
    doc_id: str,
    body: ChatMessageRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncDatabase = Depends(get_db),
):
    """Stream Q&A response for a document via SSE."""
    user_id = str(current_user["_id"])
    query = body.query.strip()

    if not query:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Query cannot be empty")

    # Verify document access
    doc = await get_document(db, user_id, doc_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Get chat history (last 6 messages)
    history, _ = await service.get_chat_history(db, user_id, doc_id, skip=0, limit=6)
    formatted_history = service.format_history_for_rag(history)

    # Save user message
    await service.save_user_message(db, user_id, doc_id, "user_doc", query)

    async def generate_stream():
        """Generate SSE events for streaming response."""
        try:
            # Call existing RAG pipeline
            from app.rag.pipeline import answer_question
            from app.models.document import AskRequest

            ask_request = AskRequest(
                question=query,
                history=formatted_history,
                document_ids=[doc.get("qdrant_doc_id") or doc_id]
            )

            response = answer_question(ask_request)

            # Stream answer tokens
            answer = response.answer
            for i in range(0, len(answer), 20):  # Simulate token streaming
                chunk = answer[i:i+20]
                yield f'data: {{"type": "token", "content": "{chunk.replace(chr(34), chr(92)+chr(34))}"}}\n\n'

            # Stream source chunks/citations
            if response.citations:
                sources = []
                for citation in response.citations:
                    sources.append({
                        "page": citation.page_number,
                        "preview": citation.quote[:100],
                        "score": 0.9
                    })
                yield f'data: {{"type": "sources", "sources": {sources}}}\n\n'

            # Stream metadata
            yield f'data: {{"type": "metadata", "query_type": "{response.query_type or "fact"}", "coverage_complete": {str(response.coverage_complete or False).lower()}}}\n\n'

            # Stream done signal
            yield f'data: {{"type": "done"}}\n\n'

            # Save assistant message
            source_chunks = []
            if response.citations:
                for citation in response.citations:
                    source_chunks.append({
                        "page": citation.page_number,
                        "preview": citation.quote[:100],
                        "score": 0.9
                    })

            await service.save_assistant_message(
                db,
                user_id,
                doc_id,
                "user_doc",
                response.answer,
                source_chunks=source_chunks,
                query_type=response.query_type
            )

        except Exception as e:
            logger.error(f"Chat streaming error for user {user_id}, doc {doc_id}: {e}")
            yield f'data: {{"type": "error", "message": "{str(e)}"}}\n\n'

    return StreamingResponse(generate_stream(), media_type="text/event-stream")


@router.get("/{doc_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    doc_id: str,
    skip: int = 0,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
    db: AsyncDatabase = Depends(get_db),
):
    """Get chat history for a document."""
    user_id = str(current_user["_id"])

    # Verify document access
    doc = await get_document(db, user_id, doc_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    messages, total = await service.get_chat_history(db, user_id, doc_id, skip, limit)

    # Convert to response format
    message_list = []
    for msg in reversed(messages):  # Reverse to chronological order
        message_list.append({
            "role": msg["role"],
            "content": msg["content"],
            "source_chunks": msg.get("source_chunks"),
            "query_type": msg.get("query_type"),
            "created_at": msg.get("created_at")
        })

    return ChatHistoryResponse(
        messages=message_list,
        total=total,
        has_more=(skip + limit) < total
    )


@router.delete("/{doc_id}/history", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_history(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncDatabase = Depends(get_db),
):
    """Delete chat history for a document."""
    user_id = str(current_user["_id"])

    # Verify document access
    doc = await get_document(db, user_id, doc_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    await service.delete_chat_history(db, user_id, doc_id)
