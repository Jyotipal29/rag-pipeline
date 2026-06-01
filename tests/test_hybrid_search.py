from app.models.document import Chunk
from app.retrieval import keyword_index
from app.retrieval.fusion import reciprocal_rank_fusion
from app.models.document import RetrievedChunk


def test_rrf_merges_dense_and_keyword():
    dense = [
        RetrievedChunk(
            chunk_id="a",
            document_id="d",
            filename="f.pdf",
            page_number=1,
            chunk_index=0,
            text="dense only",
            char_start=0,
            char_end=9,
            score=0.9,
            retrieval_source="dense",
        )
    ]
    keyword = [
        RetrievedChunk(
            chunk_id="b",
            document_id="d",
            filename="f.pdf",
            page_number=2,
            chunk_index=0,
            text="keyword hit",
            char_start=0,
            char_end=11,
            score=1.5,
            retrieval_source="keyword",
        )
    ]
    fused = reciprocal_rank_fusion([dense, keyword], limit=2, k=60)
    ids = {chunk.chunk_id for chunk in fused}
    assert ids == {"a", "b"}


def test_keyword_search_returns_matches():
    chunks = [
        Chunk(
            chunk_id="x:p1:c0",
            document_id="x",
            filename="offer.pdf",
            page_number=1,
            chunk_index=0,
            text="relieving letter from previous employer",
            char_start=0,
            char_end=40,
            token_count=5,
        )
    ]
    keyword_index.rebuild_keyword_index(chunks)
    results = keyword_index.search_keyword("relieving letter", limit=3)
    assert len(results) == 1
    assert results[0].retrieval_source == "keyword"
