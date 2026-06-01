from app.config.settings import get_settings
from app.generation.openai_chat import chat_json_completion
from app.models.retrieval import RetrievalPlan
from app.rag.prompts import PLANNER_SYSTEM_PROMPT
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _dedupe_queries(queries: list[str], max_count: int) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        normalized = query.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(query.strip())
        if len(unique) >= max_count:
            break
    return unique


def plan_retrieval(question: str) -> RetrievalPlan:
    settings = get_settings()
    try:
        parsed = chat_json_completion(
            PLANNER_SYSTEM_PROMPT,
            f"Question: {question}",
        )
        concepts = [str(c).strip() for c in parsed.get("concepts", []) if str(c).strip()]
        queries = _dedupe_queries(
            [str(q) for q in parsed.get("queries", []) if str(q).strip()],
            settings.multi_query_max - 1,
        )
    except Exception as exc:
        logger.warning("Retrieval planning failed: %s", exc)
        concepts = []
        queries = []

    # Always include the original question as the first retrieval query
    all_queries = _dedupe_queries([question, *queries], settings.multi_query_max)
    return RetrievalPlan(concepts=concepts, queries=all_queries)
