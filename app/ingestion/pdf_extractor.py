from pathlib import Path

import fitz

from app.models.document import Page
from app.utils.logger import get_logger

logger = get_logger(__name__)


def extract_pages_from_pdf(
    file_path: Path,
    document_id: str,
    filename: str,
) -> list[Page]:
    """Extract text page-by-page using PyMuPDF, preserving reading order."""
    pages: list[Page] = []

    with fitz.open(file_path) as pdf:
        for page_index in range(len(pdf)):
            page = pdf[page_index]
            text = page.get_text("text").strip()
            pages.append(
                Page(
                    page_number=page_index + 1,
                    text=text,
                    char_count=len(text),
                )
            )

    logger.info(
        "Extracted %s pages from %s",
        len(pages),
        filename,
        extra={"document_id": document_id},
    )
    return pages
