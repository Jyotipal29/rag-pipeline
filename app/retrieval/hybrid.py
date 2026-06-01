from app.config.settings import get_settings
from app.models.document import RetrievedChunk
from app.retrieval import keyword_index
from app.retrieval.fusion import reciprocal_rank_fusion
from app.vectorstore.qdrant_client import search_chunks_dense


def _hit_to_retrieved(hit, source: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        filename=hit.filename,
        page_number=hit.page_number,
        chunk_index=hit.chunk_index,
        text=hit.text,
        char_start=hit.char_start,
        char_end=hit.char_end,
        score=hit.score,
        retrieval_source=source,
        parent_chunk_id=getattr(hit, "parent_chunk_id", "") or "",
        section_title=getattr(hit, "section_title", "") or "",
        parent_text=getattr(hit, "parent_text", "") or "",
    )


def search_hybrid(
    query: str,
    limit: int,
    document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    settings = get_settings()
    dense_hits = search_chunks_dense(query, limit=limit, document_ids=document_ids)
    dense = [_hit_to_retrieved(hit, "dense") for hit in dense_hits]

    if not settings.hybrid_enabled:
        return dense

    keyword = keyword_index.search_keyword(query, limit=limit, document_ids=document_ids)
    if not keyword:
        return dense

    return reciprocal_rank_fusion(
        [dense, keyword],
        limit=limit,
        k=settings.rrf_k,
    )
