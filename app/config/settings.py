from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="Research RAG Assistant", alias="APP_NAME")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    data_dir: Path = Field(default=PROJECT_ROOT / "data", alias="DATA_DIR")
    raw_dir: Path = Field(default=PROJECT_ROOT / "data" / "raw", alias="RAW_DIR")
    processed_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "processed",
        alias="PROCESSED_DIR",
    )

    gradio_host: str = Field(default="127.0.0.1", alias="GRADIO_HOST")
    gradio_port: int = Field(default=7860, alias="GRADIO_PORT")
    api_base_url: str = Field(default="http://127.0.0.1:8000", alias="API_BASE_URL")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")
    embedding_batch_size: int = Field(default=64, alias="EMBEDDING_BATCH_SIZE")

    qdrant_url: str = Field(default="http://127.0.0.1:6333", alias="QDRANT_URL")
    qdrant_collection: str = Field(default="research_chunks", alias="QDRANT_COLLECTION")
    vector_size: int = Field(default=1536, alias="VECTOR_SIZE")

    chunk_size_tokens: int = Field(default=512, alias="CHUNK_SIZE_TOKENS")
    chunk_overlap_tokens: int = Field(default=64, alias="CHUNK_OVERLAP_TOKENS")

    def ensure_data_dirs(self) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_data_dirs()
    return settings
