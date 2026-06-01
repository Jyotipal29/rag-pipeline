"""OCR fallback for scanned or image-heavy PDF pages."""

from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def ocr_page_image(page) -> str:
    """Run Tesseract on a PyMuPDF page pixmap. Requires tesseract binary."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise ImportError(
            "OCR requires pytesseract and Pillow. Install: pip install pytesseract Pillow"
        ) from exc

    pix = page.get_pixmap(dpi=200)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return pytesseract.image_to_string(image).strip()


def maybe_ocr_page_text(page, text: str) -> str:
    settings = get_settings()
    if not settings.ocr_enabled:
        return text
    if len(text.strip()) >= settings.ocr_min_char_count:
        return text

    try:
        ocr_text = ocr_page_image(page)
        if ocr_text:
            logger.info("OCR extracted %s chars on page %s", len(ocr_text), page.number + 1)
            return ocr_text
    except Exception as exc:
        logger.warning("OCR failed for page %s: %s", page.number + 1, exc)

    return text
