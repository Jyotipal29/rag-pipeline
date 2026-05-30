import hashlib
import json
import os
import tempfile
from pathlib import Path

from app.config.settings import Settings, get_settings
from app.models.document import IngestionResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


def compute_document_id(file_bytes: bytes) -> str:
    """Content-hash ID: same PDF bytes always yield the same document_id."""
    return hashlib.sha256(file_bytes).hexdigest()


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_path, target)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _atomic_write_json(target: Path, payload: dict) -> None:
    encoded = json.dumps(payload, indent=2, default=str).encode("utf-8")
    _atomic_write_bytes(target, encoded)


def save_raw_pdf(
    file_bytes: bytes,
    document_id: str,
    settings: Settings | None = None,
) -> Path:
    settings = settings or get_settings()
    raw_path = settings.raw_dir / f"{document_id}.pdf"
    _atomic_write_bytes(raw_path, file_bytes)
    logger.info("Saved raw PDF to %s", raw_path, extra={"document_id": document_id})
    return raw_path


def save_ingestion_result(
    result: IngestionResult,
    settings: Settings | None = None,
) -> Path:
    settings = settings or get_settings()
    processed_path = settings.processed_dir / f"{result.document_id}.json"
    _atomic_write_json(processed_path, result.model_dump(mode="json"))
    logger.info(
        "Saved ingestion JSON to %s",
        processed_path,
        extra={"document_id": result.document_id},
    )
    return processed_path


def load_ingestion_result(
    document_id: str,
    settings: Settings | None = None,
) -> IngestionResult | None:
    settings = settings or get_settings()
    processed_path = settings.processed_dir / f"{document_id}.json"
    if not processed_path.exists():
        return None
    data = json.loads(processed_path.read_text(encoding="utf-8"))
    return IngestionResult.model_validate(data)
