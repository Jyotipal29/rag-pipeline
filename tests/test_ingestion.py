import hashlib
from io import BytesIO

import fitz
import pytest

from app.ingestion.ingestor import ingest_pdf_bytes
from app.ingestion.storage import compute_document_id, load_ingestion_result


def _make_minimal_pdf(text: str = "Hello Research RAG") -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    payload = doc.tobytes()
    doc.close()
    return payload


def test_compute_document_id_is_stable():
    pdf_bytes = _make_minimal_pdf()
    assert compute_document_id(pdf_bytes) == compute_document_id(pdf_bytes)
    assert len(compute_document_id(pdf_bytes)) == 64


def test_ingest_pdf_bytes_extracts_pages(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    raw_dir.mkdir()
    processed_dir.mkdir()
    monkeypatch.setenv("RAW_DIR", str(raw_dir))
    monkeypatch.setenv("PROCESSED_DIR", str(processed_dir))

    from app.config.settings import get_settings

    get_settings.cache_clear()

    pdf_bytes = _make_minimal_pdf("Page one content")
    result = ingest_pdf_bytes(pdf_bytes, "sample.pdf")

    assert result.page_count == 1
    assert result.pages[0].page_number == 1
    assert "Page one content" in result.pages[0].text
    assert result.document_id == hashlib.sha256(pdf_bytes).hexdigest()

    loaded = load_ingestion_result(result.document_id)
    assert loaded is not None
    assert loaded.document_id == result.document_id


def test_ingest_endpoint(client):
    pdf_bytes = _make_minimal_pdf("API ingest test")
    response = client.post(
        "/ingest",
        files={"file": ("test.pdf", BytesIO(pdf_bytes), "application/pdf")},
        params={"index": "false"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["page_count"] == 1
    assert body["document_id"] == hashlib.sha256(pdf_bytes).hexdigest()
    assert "API ingest test" in body["pages"][0]["text"]


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
