from pathlib import Path

import fitz

from app.ingestion.ocr import maybe_ocr_page_text
from app.models.document import Page
from app.utils.logger import get_logger

logger = get_logger(__name__)


def extract_pages_from_pdf(
    file_path: Path,
    document_id: str,
    filename: str,
) -> list[Page]:
    """Extract text page-by-page using PyMuPDF; OCR when page text is sparse."""
    pages: list[Page] = []

    with fitz.open(file_path) as pdf:
        for page_index in range(len(pdf)):
            page = pdf[page_index]
            text = page.get_text("text").strip()
            text = maybe_ocr_page_text(page, text)
            pages.append(
                Page(
                    page_number=page_index + 1,
                    text=text,
                    char_count=len(text),
                )
            )

    logger.info("Extracted %s pages from %s", len(pages), filename)
    return pages
