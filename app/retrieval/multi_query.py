from app.config.settings import get_settings
from app.models.document import RetrievedChunk
from app.models.retrieval import RetrievalPlan, RetrievalProfile
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.hybrid import search_hybrid
from app.utils.logger import get_logger

logger = get_logger(__name__)


def search_multi_query(
    plan: RetrievalPlan,
    profile: RetrievalProfile,
    document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    settings = get_settings()
    ranked_lists: list[list[RetrievedChunk]] = []

    for index, query in enumerate(plan.queries):
        hits = search_hybrid(query, limit=profile.per_query_limit, document_ids=document_ids)
        tagged = [
            chunk.model_copy(
                update={
                    "retrieval_source": (
                        f"{chunk.retrieval_source}+mq{index}"
                        if chunk.retrieval_source
                        else f"mq{index}"
                    )
                }
            )
            for chunk in hits
        ]
        ranked_lists.append(tagged)
        logger.info("Multi-query %s retrieved %s chunks for: %s", index, len(tagged), query[:80])

    merged = reciprocal_rank_fusion(
        ranked_lists,
        limit=profile.retrieval_k,
        k=settings.rrf_k,
        source_prefix="mq",
    )
    return merged


def retrieve_with_profile(
    question: str,
    profile: RetrievalProfile,
    plan: RetrievalPlan | None = None,
    document_ids: list[str] | None = None,
) -> tuple[list[RetrievedChunk], RetrievalPlan | None]:
    if profile.multi_query_enabled and plan is not None and len(plan.queries) > 1:
        chunks = search_multi_query(plan, profile, document_ids=document_ids)
        return chunks, plan

    chunks = search_hybrid(question, limit=profile.retrieval_k, document_ids=document_ids)
    return chunks, plan
