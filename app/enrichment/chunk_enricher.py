from app.config.settings import get_settings
from app.generation.openai_chat import chat_json_completion
from app.models.document import Chunk
from app.utils.logger import get_logger

logger = get_logger(__name__)

ENRICH_SYSTEM = """For each document chunk, produce JSON with key "chunks" as an array of objects:
- index: integer (0-based position in the input list)
- summary: one sentence describing what this chunk discusses
- topics: array of 3-8 topic/concept strings (synonyms welcome)
- entities: array of named entities (people, orgs, dates, amounts) if any

Be domain-agnostic. Topics should help retrieval when users ask with different words."""


def _enrich_batch(batch: list[Chunk], filename: str) -> None:
    numbered = "\n\n".join(
        f"[{i}]\n{chunk.text[:1500]}" for i, chunk in enumerate(batch)
    )
    parsed = chat_json_completion(
        ENRICH_SYSTEM,
        f"Document: {filename}\n\nChunks:\n{numbered}",
    )
    for item in parsed.get("chunks", []):
        index = int(item.get("index", -1))
        if index < 0 or index >= len(batch):
            continue
        chunk = batch[index]
        summary = str(item.get("summary", "")).strip()
        topics = [str(t).strip() for t in item.get("topics", []) if str(t).strip()]
        entities = [str(e).strip() for e in item.get("entities", []) if str(e).strip()]
        chunk.summary = summary
        chunk.topics = topics[:12]
        chunk.entities = entities[:20]
        chunk.embedding_text = chunk.text_for_embedding()


def enrich_chunks(chunks: list[Chunk], filename: str) -> list[Chunk]:
    settings = get_settings()
    if not settings.enrichment_enabled:
        for chunk in chunks:
            if chunk.chunk_role == "child" and not chunk.embedding_text:
                chunk.embedding_text = chunk.text_for_embedding()
        return chunks

    children = [c for c in chunks if c.chunk_role == "child"]
    batch_size = settings.enrichment_batch_size

    for start in range(0, len(children), batch_size):
        batch = children[start : start + batch_size]
        try:
            _enrich_batch(batch, filename)
        except Exception as exc:
            logger.warning("Enrichment batch failed: %s", exc)
            for chunk in batch:
                chunk.embedding_text = chunk.text_for_embedding()

    for chunk in chunks:
        if chunk.chunk_role == "child" and not chunk.embedding_text:
            chunk.embedding_text = chunk.text_for_embedding()

    return chunks
