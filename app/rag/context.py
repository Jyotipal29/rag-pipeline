from app.models.document import Citation, RetrievedChunk


def build_context(chunks: list[RetrievedChunk]) -> str:
    blocks: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        blocks.append(
            f"[{index}]\n"
            f"filename: {chunk.filename}\n"
            f"page_number: {chunk.page_number}\n"
            f"chunk_id: {chunk.chunk_id}\n"
            f"text:\n{chunk.text}"
        )
    return "\n\n".join(blocks)


def build_citations(chunks: list[RetrievedChunk], quote_max_len: int = 500) -> list[Citation]:
    return [
        Citation(
            citation_id=index,
            document_id=chunk.document_id,
            filename=chunk.filename,
            page_number=chunk.page_number,
            chunk_id=chunk.chunk_id,
            quote=chunk.text[:quote_max_len],
        )
        for index, chunk in enumerate(chunks, start=1)
    ]
