import re

from rank_bm25 import BM25Okapi

from app.models.document import Chunk, RetrievedChunk

TOKEN_RE = re.compile(r"\b\w+\b")

_chunks: list[Chunk] = []
_bm25: BM25Okapi | None = None


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def rebuild_keyword_index(chunks: list[Chunk]) -> None:
    global _chunks, _bm25
    indexable = [c for c in chunks if c.chunk_role == "child"] or list(chunks)
    _chunks = indexable
    tokenized = [tokenize(chunk.searchable_text()) for chunk in _chunks]
    _bm25 = BM25Okapi(tokenized) if tokenized else None


def add_chunks(chunks: list[Chunk]) -> None:
    if not chunks:
        return
    new_children = [c for c in chunks if c.chunk_role == "child"] or chunks
    rebuild_keyword_index([*_chunks, *new_children])


def has_chunks() -> bool:
    return bool(_chunks)


def search_keyword(
    query: str,
    limit: int = 8,
    document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    if _bm25 is None or not _chunks:
        return []

    allowed = set(document_ids) if document_ids else None
    scores = _bm25.get_scores(tokenize(query))
    ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)

    results: list[RetrievedChunk] = []
    for index, score in ranked:
        if score <= 0 and results:
            break
        chunk = _chunks[index]
        if allowed is not None and chunk.document_id not in allowed:
            continue
        results.append(
            RetrievedChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                filename=chunk.filename,
                page_number=chunk.page_number,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                score=float(score),
                retrieval_source="keyword",
                parent_chunk_id=chunk.parent_chunk_id,
                section_title=chunk.section_title,
                parent_text=chunk.parent_text,
            )
        )
        if len(results) >= limit:
            break
    return results
