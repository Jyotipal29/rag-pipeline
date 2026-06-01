from unittest.mock import patch

from app.models.document import AskRequest
from app.rag.pipeline import answer_question
from app.retrieval import keyword_index
from app.models.document import Chunk


def test_keyword_search_filters_by_document_id():
    chunks = [
        Chunk(
            chunk_id="a:p1:c0",
            document_id="doc-a",
            filename="a.pdf",
            page_number=1,
            chunk_index=0,
            text="termination clause in contract A",
            char_start=0,
            char_end=30,
            token_count=5,
        ),
        Chunk(
            chunk_id="b:p1:c0",
            document_id="doc-b",
            filename="b.pdf",
            page_number=1,
            chunk_index=0,
            text="termination clause in contract B",
            char_start=0,
            char_end=30,
            token_count=5,
        ),
    ]
    keyword_index.rebuild_keyword_index(chunks)
    results = keyword_index.search_keyword("termination", limit=5, document_ids=["doc-a"])
    assert len(results) == 1
    assert results[0].document_id == "doc-a"


@patch("app.rag.pipeline.collection_has_chunks", return_value=True)
@patch("app.rag.pipeline._has_keyword_chunks", return_value=True)
@patch("app.rag.pipeline.rewrite_query", return_value="termination")
@patch("app.rag.pipeline.retrieve_for_question")
@patch("app.rag.pipeline.rerank_chunks")
@patch("app.rag.pipeline.expand_parent_context", side_effect=lambda chunks: chunks)
@patch("app.rag.pipeline.generate_answer", return_value="Answer [1].")
def test_answer_question_passes_document_ids(
    _mock_generate,
    _mock_expand,
    mock_rerank,
    mock_retrieve,
    _mock_rewrite,
    _mock_kw,
    _mock_collection,
):
    from app.models.document import RetrievedChunk
    from app.models.retrieval import QueryType, RetrievalPlan, RetrievalProfile

    chunk = RetrievedChunk(
        chunk_id="doc:p1:c0",
        document_id="doc-a",
        filename="a.pdf",
        page_number=1,
        chunk_index=0,
        text="termination",
        char_start=0,
        char_end=5,
        score=0.9,
    )
    mock_retrieve.return_value = (
        [chunk],
        RetrievalProfile(
            query_type=QueryType.FACT_RETRIEVAL,
            retrieval_k=20,
            final_k=5,
            multi_query_enabled=False,
            per_query_limit=20,
        ),
        RetrievalPlan(queries=["termination"]),
    )
    mock_rerank.return_value = [chunk]

    answer_question(
        AskRequest(question="termination?", document_ids=["doc-a", "doc-b"])
    )

    mock_retrieve.assert_called_once()
    assert mock_retrieve.call_args.kwargs["document_ids"] == ["doc-a", "doc-b"]
