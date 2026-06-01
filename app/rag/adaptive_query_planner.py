from app.config.settings import get_settings
from app.models.retrieval import RetrievalPlan, RetrievalStrategy
from app.rag.retrieval_planner import plan_retrieval
from app.utils.logger import get_logger

logger = get_logger(__name__)


def adaptive_plan_retrieval(question: str, strategy: RetrievalStrategy) -> RetrievalPlan:
    """
    Generate retrieval plan with query count adapted to strategy.

    Query counts:
    - SIMPLE: 1-2 queries
    - COVERAGE: 2-3 queries
    - ANALYTICAL: 4-5 queries
    - DEEP_RESEARCH: 6-8 queries
    """
    settings = get_settings()

    # Map strategy to query count limits
    strategy_limits = {
        RetrievalStrategy.SIMPLE: 2,
        RetrievalStrategy.COVERAGE: 3,
        RetrievalStrategy.ANALYTICAL: 5,
        RetrievalStrategy.DEEP_RESEARCH: 8,
    }

    max_queries = strategy_limits.get(strategy, settings.multi_query_max)

    # Generate plan with existing planner (no LLM in this version)
    plan = plan_retrieval(question)

    # Limit queries to strategy-appropriate count
    original_count = len(plan.queries)
    plan.queries = plan.queries[:max_queries]

    logger.info(
        f"Adaptive query planning: strategy={strategy.value}, "
        f"original_queries={original_count}, truncated_to={len(plan.queries)}"
    )

    return plan
