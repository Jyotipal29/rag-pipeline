from unittest.mock import patch

from app.models.retrieval import QueryType, RetrievalPlan, RetrievalProfile
from app.rag.query_classifier import classify_query, profile_for_query_type
from app.rag.retrieval_planner import plan_retrieval
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.multi_query import search_multi_query
from app.models.document import RetrievedChunk


def test_heuristic_coverage_classification():
    result = classify_query("Identify every clause that gives the company authority.")
    assert result.query_type == QueryType.COVERAGE_SEARCH


def test_coverage_profile_has_higher_k():
    profile = profile_for_query_type(QueryType.COVERAGE_SEARCH)
    assert profile.retrieval_k >= 40
    assert profile.final_k >= 12
    assert profile.multi_query_enabled is True


@patch("app.rag.retrieval_planner.chat_json_completion")
def test_plan_retrieval_dedupes_queries(mock_json):
    mock_json.return_value = {
        "concepts": ["termination", "relocation"],
        "queries": [
            "company may terminate",
            "company may terminate",
            "employer relocation rights",
        ],
    }
    plan = plan_retrieval("Identify company authority clauses")
    assert len(plan.queries) <= 8
    assert plan.queries[0] == "Identify company authority clauses"
    assert len(set(q.lower() for q in plan.queries)) == len(plan.queries)


@patch("app.retrieval.multi_query.search_hybrid")
def test_multi_query_fuses_disjoint_chunks(mock_hybrid):
    def fake_search(query: str, limit: int, document_ids=None):
        if "terminate" in query:
            return [
                RetrievedChunk(
                    chunk_id="a",
                    document_id="d",
                    filename="f.pdf",
                    page_number=1,
                    chunk_index=0,
                    text="may terminate",
                    char_start=0,
                    char_end=12,
                    score=0.8,
                    retrieval_source="dense",
                )
            ]
        return [
            RetrievedChunk(
                chunk_id="b",
                document_id="d",
                filename="f.pdf",
                page_number=2,
                chunk_index=0,
                text="may relocate",
                char_start=0,
                char_end=12,
                score=0.7,
                retrieval_source="dense",
            )
        ]

    mock_hybrid.side_effect = fake_search
    plan = RetrievalPlan(queries=["authority", "company may terminate"])
    profile = RetrievalProfile(
        query_type=QueryType.COVERAGE_SEARCH,
        retrieval_k=10,
        final_k=5,
        multi_query_enabled=True,
        per_query_limit=5,
    )
    merged = search_multi_query(plan, profile)
    ids = {c.chunk_id for c in merged}
    assert ids == {"a", "b"}
