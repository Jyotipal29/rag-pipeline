from io import BytesIO
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def pdf_bytes():
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Document one content.")
    payload = doc.tobytes()
    doc.close()
    return payload


def test_batch_ingest_index_endpoint(client: TestClient, pdf_bytes):
    files = [
        ("files", ("one.pdf", BytesIO(pdf_bytes), "application/pdf")),
        ("files", ("two.pdf", BytesIO(pdf_bytes), "application/pdf")),
    ]
    with patch("app.api.routes.ingestion.ingest_and_index_many") as mock_batch:
        from app.models.document import BatchIndexingResult, IndexingResult, IngestionResult

        ingestion = IngestionResult(
            document_id="abc",
            filename="one.pdf",
            page_count=1,
            pages=[],
            raw_path="r",
            processed_path="p",
        )
        result = IndexingResult(
            document_id="abc",
            filename="one.pdf",
            page_count=1,
            chunk_count=2,
            indexed_count=2,
            ingestion=ingestion,
        )
        mock_batch.return_value = BatchIndexingResult(
            results=[result, result],
            document_ids=["abc", "abc"],
            total_indexed=4,
            total_chunks=4,
        )
        response = client.post("/ingest/index/batch", files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["total_indexed"] == 4
    assert len(body["results"]) == 2


def test_batch_ingest_requires_files(client: TestClient):
    response = client.post("/ingest/index/batch", files=[])
    assert response.status_code == 422
