"""Structure-aware chunking: page sections + parent-child chunks."""

from app.chunking.recursive_chunker import chunk_pages
from app.config.settings import get_settings
from app.models.document import Chunk, Page


def _section_title_from_page(page: Page) -> str:
    for line in page.text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) < 120:
            return stripped
        break
    return f"Page {page.page_number}"


def chunk_pages_with_structure(
    pages: list[Page],
    document_id: str,
    filename: str,
) -> list[Chunk]:
    """
    Per page: one parent chunk (full page) + token-sized child chunks linked via parent_chunk_id.
    Only child chunks are embedded; parents enable context expansion at retrieval.
    """
    all_chunks: list[Chunk] = []

    for page in pages:
        if not page.text.strip():
            continue

        section_id = f"{document_id}:p{page.page_number}:section"
        section_title = _section_title_from_page(page)
        parent_id = f"{document_id}:p{page.page_number}:parent"

        parent = Chunk(
            chunk_id=parent_id,
            document_id=document_id,
            filename=filename,
            page_number=page.page_number,
            chunk_index=0,
            text=page.text,
            char_start=0,
            char_end=len(page.text),
            token_count=0,
            section_id=section_id,
            section_title=section_title,
            parent_chunk_id="",
            chunk_role="parent",
        )
        all_chunks.append(parent)

        children = chunk_pages([page], document_id, filename)
        for child in children:
            enriched = child.model_copy(
                update={
                    "section_id": section_id,
                    "section_title": section_title,
                    "parent_chunk_id": parent_id,
                    "chunk_role": "child",
                }
            )
            all_chunks.append(enriched)

    return all_chunks


def build_chunks_for_document(
    pages: list[Page],
    document_id: str,
    filename: str,
) -> list[Chunk]:
    settings = get_settings()
    if settings.chunker_mode == "token":
        return chunk_pages(pages, document_id, filename)
    return chunk_pages_with_structure(pages, document_id, filename)
