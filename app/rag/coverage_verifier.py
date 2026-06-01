from app.config.settings import get_settings
from app.generation.openai_chat import chat_json_completion
from app.models.document import RetrievedChunk
from app.models.retrieval import RetrievalPlan
from app.retrieval.multi_query import search_multi_query
from app.models.retrieval import RetrievalProfile

VERIFY_SYSTEM = """You review whether retrieved document excerpts sufficiently cover a user question.

Return JSON only:
- complete: boolean — true if excerpts likely cover the question for a thorough answer
- missing_concepts: array of strings — concepts/areas still likely missing (empty if complete)
- rationale: short string"""


def verify_coverage(
    question: str,
    concepts: list[str],
    chunks: list[RetrievedChunk],
    draft_answer: str,
) -> tuple[bool, list[str]]:
    settings = get_settings()
    if not settings.coverage_verify_enabled:
        return True, []

    excerpt_summary = "\n".join(
        f"- p{chunk.page_number}: {chunk.text[:200]}..." for chunk in chunks[:15]
    )
    try:
        parsed = chat_json_completion(
            VERIFY_SYSTEM,
            f"Question: {question}\nConcepts sought: {concepts}\n\n"
            f"Draft answer:\n{draft_answer}\n\nExcerpts:\n{excerpt_summary}",
        )
        complete = bool(parsed.get("complete", True))
        missing = [str(c) for c in parsed.get("missing_concepts", []) if str(c).strip()]
        return complete, missing
    except Exception:
        return True, []


def supplemental_retrieval(
    missing_concepts: list[str],
    profile: RetrievalProfile,
    existing_ids: set[str],
    document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    if not missing_concepts:
        return []

    plan = RetrievalPlan(
        concepts=missing_concepts,
        queries=missing_concepts[: profile.multi_query_max],
    )
    extra = search_multi_query(plan, profile, document_ids=document_ids)
    return [chunk for chunk in extra if chunk.chunk_id not in existing_ids]
