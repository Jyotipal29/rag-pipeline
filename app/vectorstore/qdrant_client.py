from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.config.settings import get_settings
from app.embeddings.openai_embedder import embed_texts
from app.models.document import Chunk, SearchHit
from app.retrieval import keyword_index
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
        client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name="enrichment_status",
            field_schema=qmodels.PayloadSchemaType.KEYWORD,
        )
        logger.info("Created Qdrant collection %s", settings.qdrant_collection)


def upsert_chunks(chunks: list[Chunk]) -> int:
    if not chunks:
        return 0

    ensure_collection()
    settings = get_settings()
    indexable = [c for c in chunks if c.chunk_role == "child"]
    if not indexable:
        indexable = [c for c in chunks if c.text.strip()]

    vectors = embed_texts([chunk.text_for_embedding() for chunk in indexable])

    points = [
        qmodels.PointStruct(
            id=point_id_for_chunk(chunk.chunk_id),
            vector=vector,
            payload=chunk.model_dump(),
        )
        for chunk, vector in zip(indexable, vectors, strict=True)
    ]

    get_qdrant_client().upsert(
        collection_name=settings.qdrant_collection,
        points=points,
    )
    keyword_index.add_chunks(indexable)
    logger.info("Upserted %s chunks to Qdrant", len(points))
    return len(points)


def collection_has_chunks() -> bool:
    try:
        ensure_collection()
        settings = get_settings()
        info = get_qdrant_client().get_collection(settings.qdrant_collection)
        return int(getattr(info, "points_count", 0) or 0) > 0
    except Exception:
        return keyword_index.has_chunks()


def iter_all_chunks(batch_size: int = 256) -> list[Chunk]:
    ensure_collection()
    settings = get_settings()
    client = get_qdrant_client()
    offset = None
    chunks: list[Chunk] = []

    while True:
        points, offset = client.scroll(
            collection_name=settings.qdrant_collection,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            if point.payload:
                chunks.append(Chunk(**point.payload))
        if offset is None:
            break

    return chunks


def _document_filter(document_ids: list[str] | None) -> qmodels.Filter | None:
    if not document_ids:
        return None
    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="document_id",
                match=qmodels.MatchAny(any=document_ids),
            )
        ]
    )


def _enrichment_status_filter(status: str) -> qmodels.Filter | None:
    """Create a filter for enrichment_status field."""
    if not status:
        return None
    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="enrichment_status",
                match=qmodels.MatchValue(value=status),
            )
        ]
    )


def search_chunks_dense(
    query: str,
    limit: int = 5,
    document_ids: list[str] | None = None,
) -> list[SearchHit]:
    ensure_collection()
    settings = get_settings()
    vector = embed_texts([query])[0]
    client = get_qdrant_client()

    query_filter = _document_filter(document_ids)

    if hasattr(client, "query_points"):
        result = client.query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
            limit=limit,
            with_payload=True,
            query_filter=query_filter,
        )
        points = result.points
    else:
        points = client.search(
            collection_name=settings.qdrant_collection,
            query_vector=vector,
            limit=limit,
            with_payload=True,
            query_filter=query_filter,
        )

    hits: list[SearchHit] = []
    for point in points:
        payload = point.payload or {}
        if payload.get("chunk_role") == "parent":
            continue
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
                parent_chunk_id=str(payload.get("parent_chunk_id", "")),
                section_title=str(payload.get("section_title", "")),
                parent_text=str(payload.get("parent_text", "")),
            )
        )
    return hits


def search_chunks(query: str, limit: int = 5) -> list[SearchHit]:
    """Backward-compatible alias for dense search."""
    return search_chunks_dense(query, limit=limit)


def get_chunks_by_enrichment_status(
    status: str,
    document_id: str | None = None,
    limit: int = 100,
) -> list[Chunk]:
    """
    Query chunks by enrichment_status.

    Args:
        status: Enrichment status to filter by (PENDING, PROCESSING, COMPLETED, FAILED)
        document_id: Optional document_id filter
        limit: Maximum chunks to return

    Returns:
        List of chunks matching the status
    """
    ensure_collection()
    settings = get_settings()
    client = get_qdrant_client()

    conditions = [
        qmodels.FieldCondition(
            key="enrichment_status",
            match=qmodels.MatchValue(value=status),
        )
    ]

    if document_id:
        conditions.append(
            qmodels.FieldCondition(
                key="document_id",
                match=qmodels.MatchValue(value=document_id),
            )
        )

    query_filter = qmodels.Filter(must=conditions)

    points, _ = client.scroll(
        collection_name=settings.qdrant_collection,
        scroll_filter=query_filter,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )

    chunks = []
    for point in points:
        if point.payload:
            chunks.append(Chunk(**point.payload))

    return chunks


def count_chunks_by_enrichment_status(document_id: str) -> dict[str, int]:
    """
    Count chunks in each enrichment status for a document.

    Args:
        document_id: Document ID to count chunks for

    Returns:
        Dict mapping status -> count
    """
    statuses = ["PENDING", "PROCESSING", "COMPLETED", "FAILED"]
    counts = {}

    for status in statuses:
        chunks = get_chunks_by_enrichment_status(status, document_id=document_id)
        counts[status] = len(chunks)

    return counts
