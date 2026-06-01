from unittest.mock import patch

from app.chunking.structure_chunker import build_chunks_for_document
from app.enrichment.chunk_enricher import enrich_chunks
from app.indexing.pipeline import _attach_parent_text
from app.models.document import Page
from app.retrieval.parent_expand import expand_parent_context
from app.retrieval.parent_store import clear_parents, register_parents
from app.models.document import RetrievedChunk


def test_structure_chunker_creates_parent_and_children():
    pages = [
        Page(page_number=1, text="Section A\n\nBody text " * 50, char_count=100),
    ]
    chunks = build_chunks_for_document(pages, "doc1", "test.pdf")
    parents = [c for c in chunks if c.chunk_role == "parent"]
    children = [c for c in chunks if c.chunk_role == "child"]
    assert len(parents) == 1
    assert len(children) >= 1
    assert all(c.parent_chunk_id == parents[0].chunk_id for c in children)


def test_attach_parent_text_on_children():
    pages = [Page(page_number=1, text="Full page content here.", char_count=24)]
    chunks = build_chunks_for_document(pages, "doc1", "test.pdf")
    chunks = _attach_parent_text(chunks)
    child = next(c for c in chunks if c.chunk_role == "child")
    assert "Full page content" in child.parent_text


@patch("app.enrichment.chunk_enricher.chat_json_completion")
def test_enrich_chunks_sets_embedding_text(mock_json):
    mock_json.return_value = {
        "chunks": [
            {"index": 0, "summary": "A clause about termination.", "topics": ["termination"], "entities": []}
        ]
    }
    pages = [Page(page_number=1, text="The company may terminate employment.", char_count=40)]
    chunks = build_chunks_for_document(pages, "doc1", "test.pdf")
    children = [c for c in chunks if c.chunk_role == "child"]
    enriched = enrich_chunks(children, "test.pdf")
    assert enriched[0].summary
    assert enriched[0].embedding_text
    assert "termination" in enriched[0].searchable_text().lower()


def test_parent_expand_uses_store():
    from app.models.document import Chunk

    clear_parents()
    parent_id = "doc:p1:parent"
    register_parents(
        [
            Chunk(
                chunk_id=parent_id,
                document_id="doc",
                filename="t.pdf",
                page_number=1,
                chunk_index=0,
                text="Expanded parent section.",
                char_start=0,
                char_end=10,
                token_count=1,
                chunk_role="parent",
            )
        ]
    )
    child = RetrievedChunk(
        chunk_id="doc:p1:c0",
        document_id="doc",
        filename="t.pdf",
        page_number=1,
        chunk_index=0,
        text="small child",
        char_start=0,
        char_end=5,
        score=0.9,
        parent_chunk_id=parent_id,
    )
    expanded = expand_parent_context([child])
    assert "Expanded parent" in expanded[0].text
