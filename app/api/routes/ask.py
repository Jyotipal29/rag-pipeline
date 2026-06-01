from fastapi import APIRouter, HTTPException, Query, status

from app.models.document import AskRequest, AskResponse
from app.rag.pipeline import answer_question

router = APIRouter(tags=["ask"])


@router.post("/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    mode: str | None = Query(
        None,
        description="Force retrieval profile: 'coverage' uses high-recall multi-query search",
    ),
) -> AskResponse:
    if not request.question.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question must not be empty",
        )

    force_coverage = mode is not None and mode.lower() == "coverage"

    try:
        return answer_question(request, force_coverage=force_coverage)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Answer generation failed: {exc}",
        ) from exc
