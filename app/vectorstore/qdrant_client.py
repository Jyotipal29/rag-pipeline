from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.config.settings import get_settings
from app.embeddings.openai_embedder import embed_texts
from app.models.document import Chunk, SearchHit
from app.utils.logger import get_logger

logger = get_logger(__name__)

_client: QdrantClient | None = None


def get_qdrant_client() -> QdrantClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = QdrantClient(url=settings.qdrant_url)
    return _client


def close_qdrant_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def point_id_for_chunk(chunk_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, chunk_id))


def ensure_collection() -> None:
    settings = get_settings()
    client = get_qdrant_client()
    names = {c.name for c in client.get_collections().collections}

    if settings.qdrant_collection not in names:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=qmodels.VectorParams(
                size=settings.vector_size,
                distance=qmodels.Distance.COSINE,
            ),
        )
        client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name="document_id",
            field_schema=qmodels.PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name="page_number",
            field_schema=qmodels.PayloadSchemaType.INTEGER,
        )
        logger.info("Created Qdrant collection %s", settings.qdrant_collection)


def upsert_chunks(chunks: list[Chunk]) -> int:
    if not chunks:
        return 0

    ensure_collection()
    settings = get_settings()
    vectors = embed_texts([chunk.text for chunk in chunks])

    points = [
        qmodels.PointStruct(
            id=point_id_for_chunk(chunk.chunk_id),
            vector=vector,
            payload=chunk.model_dump(),
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]

    get_qdrant_client().upsert(
        collection_name=settings.qdrant_collection,
        points=points,
    )
    logger.info("Upserted %s chunks to Qdrant", len(points))
    return len(points)


def search_chunks(query: str, limit: int = 5) -> list[SearchHit]:
    ensure_collection()
    settings = get_settings()
    vector = embed_texts([query])[0]
    client = get_qdrant_client()

    if hasattr(client, "query_points"):
        result = client.query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
            limit=limit,
            with_payload=True,
        )
        points = result.points
    else:
        points = client.search(
            collection_name=settings.qdrant_collection,
            query_vector=vector,
            limit=limit,
            with_payload=True,
        )

    hits: list[SearchHit] = []
    for point in points:
        payload = point.payload or {}
        hits.append(
            SearchHit(
                chunk_id=str(payload["chunk_id"]),
                document_id=str(payload["document_id"]),
                filename=str(payload["filename"]),
                page_number=int(payload["page_number"]),
                chunk_index=int(payload["chunk_index"]),
                text=str(payload["text"]),
                char_start=int(payload.get("char_start", 0)),
                char_end=int(payload.get("char_end", len(str(payload["text"])))),
                score=float(point.score),
            )
        )
    return hits
