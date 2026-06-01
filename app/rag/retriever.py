import uuid

from app.models.document import RetrievedChunk
from app.models.retrieval import COVERAGE_QUERY_TYPES, RetrievalPlan, RetrievalProfile, RetrievalStrategy
from app.rag.query_classifier import classify_query, profile_for_query_type, profile_for_strategy
from app.rag.retrieval_planner import plan_retrieval
from app.rag.strategy_router import route_strategy
from app.retrieval.multi_query import retrieve_with_profile
from app.utils.logger import get_logger

logger = get_logger(__name__)


def retrieve_for_question(
    question: str,
    force_coverage: bool = False,
    document_ids: list[str] | None = None,
) -> tuple[list[RetrievedChunk], RetrievalProfile, RetrievalPlan | None, str, RetrievalStrategy]:
    """
    Retrieve chunks for a question with strategy-based profile selection.

    Returns:
        Tuple of (chunks, profile, plan, query_id, strategy)
    """
    query_id = str(uuid.uuid4())

    if force_coverage:
        from app.models.retrieval import QueryType

        profile = profile_for_query_type(QueryType.COVERAGE_SEARCH)
        strategy = RetrievalStrategy.COVERAGE
    else:
        # Get classification for backward compatibility
        classification = classify_query(question)
        base_profile = profile_for_query_type(classification.query_type)

        # Get strategy for profile type selection
        strategy = route_strategy(question)
        profile_type = profile_for_strategy(strategy)

        # Update profile with selected profile type
        base_profile.profile_type = profile_type
        profile = base_profile

    plan: RetrievalPlan | None = None
    if profile.multi_query_enabled or profile.query_type in COVERAGE_QUERY_TYPES:
        plan = plan_retrieval(question)

    chunks, plan = retrieve_with_profile(question, profile, plan, document_ids=document_ids)
    logger.info(
        f"Retrieval completed: strategy={strategy.value}, "
        f"profile={profile.profile_type.value}, chunks={len(chunks)}, query_id={query_id}"
    )
    return chunks, profile, plan, query_id, strategy
