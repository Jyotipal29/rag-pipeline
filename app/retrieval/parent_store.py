"""In-memory parent section texts for retrieval expansion."""

from app.models.document import Chunk

_parent_texts: dict[str, str] = {}


def register_parents(chunks: list[Chunk]) -> None:
    for chunk in chunks:
        if chunk.chunk_role == "parent":
            _parent_texts[chunk.chunk_id] = chunk.text


def get_parent_text(parent_chunk_id: str) -> str | None:
    return _parent_texts.get(parent_chunk_id)


def clear_parents() -> None:
    _parent_texts.clear()
