from app.models.document import RetrievedChunk


def reciprocal_rank_fusion(
    ranked_lists: list[list[RetrievedChunk]],
    limit: int,
    k: int,
    source_prefix: str = "",
) -> list[RetrievedChunk]:
    """Merge multiple ranked lists with RRF. Later lists can use distinct source tags."""
    if not ranked_lists:
        return []

    scores: dict[str, float] = {}
    chunks: dict[str, RetrievedChunk] = {}
    sources: dict[str, set[str]] = {}

    for list_index, ranked in enumerate(ranked_lists):
        tag = f"{source_prefix}list{list_index}" if source_prefix else ""
        for rank, chunk in enumerate(ranked, start=1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank)
            chunks[chunk.chunk_id] = chunk
            label = chunk.retrieval_source
            if tag:
                label = f"{label}+{tag}" if label else tag
            sources.setdefault(chunk.chunk_id, set()).add(label or "unknown")

    fused: list[RetrievedChunk] = []
    for chunk_id, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]:
        chunk = chunks[chunk_id].model_copy(
            update={
                "score": score,
                "retrieval_source": "+".join(sorted(sources[chunk_id])),
            }
        )
        fused.append(chunk)
    return fused
