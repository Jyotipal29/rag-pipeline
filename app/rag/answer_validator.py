from app.config.settings import get_settings
from app.generation.openai_chat import chat_json_completion

VALIDATE_SYSTEM = """Validate a grounded RAG answer against its context.

Return JSON only:
- grounded: boolean — claims supported by context with citations
- warnings: array of strings — issues (unsupported claims, thin coverage, missing citations)
- suggest_more_retrieval: boolean"""


def validate_answer(question: str, answer: str, context_preview: str) -> tuple[bool, list[str], bool]:
    settings = get_settings()
    if not settings.answer_validation_enabled:
        return True, [], False

    try:
        parsed = chat_json_completion(
            VALIDATE_SYSTEM,
            f"Question: {question}\n\nAnswer:\n{answer}\n\nContext preview:\n{context_preview[:6000]}",
        )
        grounded = bool(parsed.get("grounded", True))
        warnings = [str(w) for w in parsed.get("warnings", []) if str(w).strip()]
        suggest_more = bool(parsed.get("suggest_more_retrieval", False))
        return grounded, warnings, suggest_more
    except Exception:
        return True, [], False
