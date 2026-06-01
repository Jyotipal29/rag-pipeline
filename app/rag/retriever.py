from app.models.document import RetrievedChunk
from app.models.retrieval import COVERAGE_QUERY_TYPES, RetrievalPlan, RetrievalProfile
from app.rag.query_classifier import classify_query, profile_for_query_type
from app.rag.retrieval_planner import plan_retrieval
from app.retrieval.multi_query import retrieve_with_profile


def retrieve_for_question(
    question: str,
    force_coverage: bool = False,
    document_ids: list[str] | None = None,
) -> tuple[list[RetrievedChunk], RetrievalProfile, RetrievalPlan | None]:
    if force_coverage:
        from app.models.retrieval import QueryType

        profile = profile_for_query_type(QueryType.COVERAGE_SEARCH)
    else:
        classification = classify_query(question)
        profile = profile_for_query_type(classification.query_type)

    plan: RetrievalPlan | None = None
    if profile.multi_query_enabled or profile.query_type in COVERAGE_QUERY_TYPES:
        plan = plan_retrieval(question)

    chunks, plan = retrieve_with_profile(question, profile, plan, document_ids=document_ids)
    return chunks, profile, plan
