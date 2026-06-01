import time

from app.chunking.structure_chunker import build_chunks_for_document
from app.config.settings import get_settings
from app.enrichment.chunk_enricher import enrich_chunks
from app.models.document import Chunk, IngestionResult
from app.retrieval.parent_store import register_parents
from app.utils.logger import get_logger
from app.vectorstore.qdrant_client import upsert_chunks

logger = get_logger(__name__)


def _attach_parent_text(chunks: list[Chunk]) -> list[Chunk]:
    settings = get_settings()
    parents = {c.chunk_id: c.text for c in chunks if c.chunk_role == "parent"}
    updated: list[Chunk] = []
    for chunk in chunks:
        if chunk.chunk_role == "child" and chunk.parent_chunk_id:
            parent_body = parents.get(chunk.parent_chunk_id, "")
            updated.append(
                chunk.model_copy(
                    update={"parent_text": parent_body[: settings.parent_max_chars]}
                )
            )
        else:
            updated.append(chunk)
    return updated


def build_and_index_chunks(ingestion: IngestionResult) -> tuple[list[Chunk], int]:
    start = time.time()

    t0 = time.time()
    chunks = build_chunks_for_document(
        ingestion.pages,
        ingestion.document_id,
        ingestion.filename,
    )
    logger.info(
        "Chunked %s: %d chunks in %.2fs",
        ingestion.document_id,
        len(chunks),
        time.time() - t0,
    )

    t0 = time.time()
    chunks = enrich_chunks(chunks, ingestion.filename)
    logger.info(
        "Enriched %s in %.2fs",
        ingestion.document_id,
        time.time() - t0,
    )

    t0 = time.time()
    chunks = _attach_parent_text(chunks)
    register_parents(chunks)
    logger.info(
        "Parent expansion for %s in %.2fs",
        ingestion.document_id,
        time.time() - t0,
    )

    t0 = time.time()
    indexed = upsert_chunks(chunks)
    logger.info(
        "Upserted %s: %d chunks in %.2fs",
        ingestion.document_id,
        indexed,
        time.time() - t0,
    )

    total = time.time() - start
    logger.info(
        "Full indexing for %s complete in %.2fs",
        ingestion.document_id,
        total,
    )

    return chunks, indexed
