from app.config.settings import get_settings
from app.models.document import RetrievedChunk
from app.utils.logger import get_logger

logger = get_logger(__name__)


def rerank_chunks(query: str, chunks: list[RetrievedChunk], top_n: int) -> list[RetrievedChunk]:
    settings = get_settings()
    if not chunks:
        return []

    if not settings.rerank_enabled or not settings.cohere_api_key:
        return chunks[:top_n]

    try:
        import cohere
    except ImportError as exc:
        logger.warning("cohere package not installed; skipping rerank: %s", exc)
        return chunks[:top_n]

    client = cohere.Client(api_key=settings.cohere_api_key)
    documents = [chunk.text for chunk in chunks]

    try:
        response = client.rerank(
            model=settings.rerank_model,
            query=query,
            documents=documents,
            top_n=min(top_n, len(documents)),
        )
    except Exception as exc:
        logger.warning("Cohere rerank failed, using fusion order: %s", exc)
        return chunks[:top_n]

    reranked: list[RetrievedChunk] = []
    seen: set[str] = set()

    for result in response.results:
        chunk = chunks[result.index]
        if chunk.chunk_id in seen:
            continue
        reranked.append(
            chunk.model_copy(
                update={
                    "score": float(result.relevance_score),
                    "retrieval_source": f"{chunk.retrieval_source}+rerank",
                }
            )
        )
        seen.add(chunk.chunk_id)

    return reranked or chunks[:top_n]
