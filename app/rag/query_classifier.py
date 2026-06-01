import re

from app.config.settings import get_settings
from app.generation.openai_chat import chat_json_completion
from app.models.retrieval import (
    COVERAGE_QUERY_TYPES,
    QueryClassification,
    QueryType,
    RetrievalProfile,
    RetrievalProfileType,
    RetrievalStrategy,
)
from app.rag.prompts import CLASSIFIER_SYSTEM_PROMPT
from app.utils.logger import get_logger

logger = get_logger(__name__)

_COVERAGE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\b(every|all|each|any)\b.*\b(clause|risk|limitation|obligation|mention|section)\b",
        r"\bidentify\b.*\b(every|all)\b",
        r"\blist\b.*\b(all|every)\b",
        r"\bfind\b.*\b(all|every)\b",
        r"\bsummarize\b.*\b(all|every)\b",
        r"\bcomprehensive\b",
        r"\bcoverage\b",
        r"\bwhat are the risks\b",
        r"\ball restrictions\b",
    ]
]


def _heuristic_classification(question: str) -> QueryClassification | None:
    for pattern in _COVERAGE_PATTERNS:
        if pattern.search(question):
            return QueryClassification(
                query_type=QueryType.COVERAGE_SEARCH,
                confidence=0.85,
                rationale="Heuristic: exhaustive or coverage-style phrasing detected.",
            )
    return None


def classify_query(question: str) -> QueryClassification:
    settings = get_settings()
    if not settings.query_classification_enabled:
        return QueryClassification(
            query_type=QueryType.FACT_RETRIEVAL,
            confidence=1.0,
            rationale="Classification disabled; using fact profile.",
        )

    heuristic = _heuristic_classification(question)
    if heuristic is not None:
        return heuristic

    try:
        parsed = chat_json_completion(
            CLASSIFIER_SYSTEM_PROMPT,
            f"Question: {question}",
        )
        raw_type = str(parsed.get("query_type", QueryType.FACT_RETRIEVAL))
        try:
            query_type = QueryType(raw_type)
        except ValueError:
            query_type = QueryType.FACT_RETRIEVAL
        return QueryClassification(
            query_type=query_type,
            confidence=float(parsed.get("confidence", 0.8)),
            rationale=str(parsed.get("rationale", "")),
        )
    except Exception as exc:
        logger.warning("Query classification failed, defaulting to fact_retrieval: %s", exc)
        return QueryClassification(
            query_type=QueryType.FACT_RETRIEVAL,
            confidence=0.5,
            rationale=f"Classifier error: {exc}",
        )


def profile_for_query_type(query_type: QueryType) -> RetrievalProfile:
    settings = get_settings()
    use_coverage = query_type in COVERAGE_QUERY_TYPES

    if use_coverage:
        return RetrievalProfile(
            query_type=query_type,
            retrieval_k=settings.coverage_retrieval_k,
            final_k=settings.coverage_final_k,
            multi_query_enabled=settings.multi_query_enabled,
            multi_query_max=settings.multi_query_max,
            per_query_limit=settings.coverage_per_query_limit,
        )

    return RetrievalProfile(
        query_type=query_type,
        retrieval_k=settings.retrieval_k,
        final_k=settings.final_k,
        multi_query_enabled=False,
        multi_query_max=settings.multi_query_max,
        per_query_limit=settings.retrieval_k,
    )


def profile_for_strategy(strategy: RetrievalStrategy) -> RetrievalProfileType:
    """Map RetrievalStrategy to RetrievalProfileType."""
    strategy_to_profile = {
        RetrievalStrategy.SIMPLE: RetrievalProfileType.FAST,
        RetrievalStrategy.COVERAGE: RetrievalProfileType.BALANCED,
        RetrievalStrategy.ANALYTICAL: RetrievalProfileType.RESEARCH,
        RetrievalStrategy.DEEP_RESEARCH: RetrievalProfileType.RESEARCH,
    }
    return strategy_to_profile.get(strategy, RetrievalProfileType.BALANCED)
