import tiktoken

from app.config.settings import get_settings
from app.models.document import Chunk, Page


def _get_encoding() -> tiktoken.Encoding:
    settings = get_settings()
    try:
        return tiktoken.encoding_for_model(settings.embedding_model)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str, encoding: tiktoken.Encoding) -> int:
    return len(encoding.encode(text))


def _split_text_recursive(
    text: str,
    encoding: tiktoken.Encoding,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """Recursively split text until each piece fits within chunk_size tokens."""
    if _count_tokens(text, encoding) <= chunk_size:
        return [text] if text.strip() else []

    separators = ["\n\n", "\n", ". ", " ", ""]
    for separator in separators:
        if separator:
            parts = text.split(separator)
            if len(parts) == 1:
                continue
        else:
            # Character-level fallback for very long tokens
            mid = len(text) // 2
            parts = [text[:mid], text[mid:]]

        chunks: list[str] = []
        current = ""
        for part in parts:
            candidate = separator.join(filter(None, [current, part])) if current else part
            if _count_tokens(candidate, encoding) <= chunk_size:
                current = candidate
            else:
                if current.strip():
                    chunks.extend(
                        _split_text_recursive(current, encoding, chunk_size, chunk_overlap)
                    )
                current = part
        if current.strip():
            chunks.extend(
                _split_text_recursive(current, encoding, chunk_size, chunk_overlap)
            )
        if chunks:
            return chunks

    # Hard split by token windows
    tokens = encoding.encode(text)
    windows: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        windows.append(encoding.decode(tokens[start:end]))
        if end >= len(tokens):
            break
        start = max(0, end - chunk_overlap)
    return windows


def chunk_pages(
    pages: list[Page],
    document_id: str,
    filename: str,
    chunk_size_tokens: int | None = None,
    chunk_overlap_tokens: int | None = None,
) -> list[Chunk]:
    settings = get_settings()
    chunk_size = chunk_size_tokens or settings.chunk_size_tokens
    chunk_overlap = chunk_overlap_tokens or settings.chunk_overlap_tokens
    encoding = _get_encoding()

    chunks: list[Chunk] = []
    for page in pages:
        if not page.text.strip():
            continue

        text_segments = _split_text_recursive(
            page.text,
            encoding,
            chunk_size,
            chunk_overlap,
        )

        search_start = 0
        for chunk_index, segment in enumerate(text_segments):
            segment = segment.strip()
            if not segment:
                continue

            char_start = page.text.find(segment, search_start)
            if char_start < 0:
                char_start = search_start
            char_end = char_start + len(segment)
            search_start = char_end

            chunk_id = f"{document_id}:p{page.page_number}:c{chunk_index}"
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    filename=filename,
                    page_number=page.page_number,
                    chunk_index=chunk_index,
                    text=segment,
                    char_start=char_start,
                    char_end=char_end,
                    token_count=_count_tokens(segment, encoding),
                )
            )

    return chunks
