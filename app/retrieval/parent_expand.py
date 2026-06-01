from app.config.settings import get_settings
from app.models.document import RetrievedChunk
from app.retrieval.parent_store import get_parent_text


def expand_parent_context(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Replace child chunk text with parent section text when available (deduped)."""
    settings = get_settings()
    if not settings.parent_expand_enabled:
        return chunks

    expanded: list[RetrievedChunk] = []
    seen_parents: set[str] = set()

    for chunk in chunks:
        parent_id = chunk.parent_chunk_id
        if parent_id and parent_id not in seen_parents:
            parent_text = get_parent_text(parent_id) or chunk.parent_text
            if parent_text:
                seen_parents.add(parent_id)
                trimmed = parent_text[: settings.parent_max_chars]
                expanded.append(
                    chunk.model_copy(
                        update={
                            "text": trimmed,
                            "chunk_id": parent_id,
                        }
                    )
                )
                continue

        expanded.append(chunk)

    return expanded
