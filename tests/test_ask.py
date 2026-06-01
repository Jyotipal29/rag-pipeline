from unittest.mock import patch

import pytest

from app.models.document import AskRequest, RetrievedChunk
from app.rag.pipeline import answer_question


def _sample_chunk(chunk_id: str = "doc:p1:c0") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="doc",
        filename="test.pdf",
        page_number=1,
        chunk_index=0,
        text="The employee reports to the HR Director.",
        char_start=0,
        char_end=40,
        score=0.9,
        retrieval_source="dense",
    )


@patch("app.rag.pipeline.collection_has_chunks", return_value=True)
@patch("app.rag.pipeline._has_keyword_chunks", return_value=True)
@patch("app.rag.pipeline.rewrite_query", return_value="manager reporting line")
@patch("app.rag.pipeline.retrieve_for_question")
@patch("app.rag.pipeline.rerank_chunks")
@patch("app.rag.pipeline.expand_parent_context", side_effect=lambda chunks: chunks)
@patch("app.rag.pipeline.generate_answer")
def test_answer_question_returns_citations(
    mock_generate,
    _mock_expand,
    mock_rerank,
    mock_retrieve,
    _mock_rewrite,
    _mock_kw,
    _mock_collection,
):
    from app.models.retrieval import QueryType, RetrievalPlan, RetrievalProfile

    chunk = _sample_chunk()
    mock_retrieve.return_value = (
        [chunk],
        RetrievalProfile(
            query_type=QueryType.FACT_RETRIEVAL,
            retrieval_k=20,
            final_k=5,
            multi_query_enabled=False,
            per_query_limit=20,
        ),
        RetrievalPlan(queries=["Who is the manager?"]),
    )
    mock_rerank.return_value = [chunk]
    mock_generate.return_value = "The employee reports to the HR Director [1]."

    response = answer_question(AskRequest(question="Who is the manager?"))

    assert "[1]" in response.answer
    assert len(response.citations) == 1
    assert response.citations[0].page_number == 1
    assert response.retrieved_chunks[0].chunk_id == chunk.chunk_id


@patch("app.rag.pipeline.collection_has_chunks", return_value=False)
@patch("app.rag.pipeline._has_keyword_chunks", return_value=False)
def test_answer_question_no_index(_mock_kw, _mock_collection):
    response = answer_question(AskRequest(question="Hello?"))
    assert "No indexed" in response.answer
    assert response.citations == []


def test_ask_endpoint_empty_question(client):
    response = client.post("/ask", json={"question": "   "})
    assert response.status_code == 400


@patch("app.api.routes.ask.answer_question")
def test_ask_endpoint_success(mock_answer, client):
    from app.models.document import AskResponse, Citation

    mock_answer.return_value = AskResponse(
        question="Who is the manager?",
        answer="HR Director [1].",
        citations=[
            Citation(
                citation_id=1,
                document_id="doc",
                filename="test.pdf",
                page_number=1,
                chunk_id="doc:p1:c0",
                quote="HR Director",
            )
        ],
        retrieved_chunks=[_sample_chunk()],
    )
    response = client.post("/ask", json={"question": "Who is the manager?"})
    assert response.status_code == 200
    assert response.json()["answer"] == "HR Director [1]."
