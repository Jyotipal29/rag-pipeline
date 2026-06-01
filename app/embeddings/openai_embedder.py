from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _get_client() -> OpenAI:
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError(
            "OPENAI_API_KEY is not set. Add it to .env before indexing or searching."
        )
    return OpenAI(api_key=settings.openai_api_key)


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _embed_batch(texts: list[str], model: str) -> list[list[float]]:
    client = _get_client()
    response = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts in batches with retries and cost-aware logging."""
    if not texts:
        return []

    settings = get_settings()
    batch_size = settings.embedding_batch_size
    all_vectors: list[list[float]] = []

    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors = _embed_batch(batch, settings.embedding_model)
        all_vectors.extend(vectors)
        logger.info(
            "Embedded batch %s-%s (%s texts)",
            start,
            start + len(batch),
            len(batch),
        )

    return all_vectors
