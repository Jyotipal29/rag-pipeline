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
    embedding_batch_size: int = Field(default=256, alias="EMBEDDING_BATCH_SIZE")

    qdrant_url: str = Field(default="http://127.0.0.1:6333", alias="QDRANT_URL")
    qdrant_collection: str = Field(default="research_chunks", alias="QDRANT_COLLECTION")
    vector_size: int = Field(default=1536, alias="VECTOR_SIZE")

    chunk_size_tokens: int = Field(default=512, alias="CHUNK_SIZE_TOKENS")
    chunk_overlap_tokens: int = Field(default=64, alias="CHUNK_OVERLAP_TOKENS")
    chunker_mode: str = Field(default="structure", alias="CHUNKER_MODE")

    # Phase 2 — generation
    chat_model: str = Field(default="gpt-4o-mini", alias="CHAT_MODEL")
    chat_max_tokens: int = Field(default=1024, alias="CHAT_MAX_TOKENS")
    generation_temperature: float = Field(default=0.0, alias="GENERATION_TEMPERATURE")

    # Phase 2 — retrieval
    retrieval_k: int = Field(default=20, alias="RETRIEVAL_K")
    final_k: int = Field(default=5, alias="FINAL_K")
    hybrid_enabled: bool = Field(default=True, alias="HYBRID_ENABLED")
    rrf_k: int = Field(default=60, alias="RRF_K")

    rerank_enabled: bool = Field(default=True, alias="RERANK_ENABLED")
    cohere_api_key: str | None = Field(default=None, alias="COHERE_API_KEY")
    rerank_model: str = Field(default="rerank-v3.5", alias="RERANK_MODEL")

    # Phase 3A — coverage retrieval
    query_classification_enabled: bool = Field(default=True, alias="QUERY_CLASSIFICATION_ENABLED")
    multi_query_enabled: bool = Field(default=True, alias="MULTI_QUERY_ENABLED")
    multi_query_max: int = Field(default=8, alias="MULTI_QUERY_MAX")
    coverage_retrieval_k: int = Field(default=40, alias="COVERAGE_RETRIEVAL_K")
    coverage_final_k: int = Field(default=12, alias="COVERAGE_FINAL_K")
    coverage_per_query_limit: int = Field(default=15, alias="COVERAGE_PER_QUERY_LIMIT")

    # Phase 3B — enrichment
    enrichment_enabled: bool = Field(default=True, alias="ENRICHMENT_ENABLED")
    enrichment_batch_size: int = Field(default=8, alias="ENRICHMENT_BATCH_SIZE")

    # Phase 3C — parent expansion
    parent_expand_enabled: bool = Field(default=True, alias="PARENT_EXPAND_ENABLED")
    parent_max_chars: int = Field(default=4000, alias="PARENT_MAX_CHARS")

    # Phase 3D — verification
    coverage_verify_enabled: bool = Field(default=True, alias="COVERAGE_VERIFY_ENABLED")
    coverage_max_rounds: int = Field(default=1, alias="COVERAGE_MAX_ROUNDS")
    answer_validation_enabled: bool = Field(default=True, alias="ANSWER_VALIDATION_ENABLED")

    # OCR
    ocr_enabled: bool = Field(default=True, alias="OCR_ENABLED")
    ocr_min_char_count: int = Field(default=50, alias="OCR_MIN_CHAR_COUNT")

    # Celery + Redis (U3 — background enrichment)
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="", alias="CELERY_RESULT_BACKEND")
    celery_task_always_eager: bool = Field(
        default=False,
        alias="CELERY_TASK_ALWAYS_EAGER",
        description="If true, execute tasks synchronously (for testing)",
    )
    enrichment_task_max_retries: int = Field(
        default=3, alias="ENRICHMENT_TASK_MAX_RETRIES"
    )
    enrichment_task_retry_backoff: int = Field(
        default=60, alias="ENRICHMENT_TASK_RETRY_BACKOFF", description="Seconds between retries"
    )

    # MongoDB (DocMind backend)
    mongodb_url: str = Field(default="mongodb://localhost:27017", alias="MONGODB_URL")
    mongodb_db_name: str = Field(default="docmind", alias="MONGODB_DB_NAME")

    # JWT authentication
    jwt_secret: str = Field(default="", alias="JWT_SECRET", description="Secret key for access tokens (min 32 chars)")
    jwt_refresh_secret: str = Field(default="", alias="JWT_REFRESH_SECRET", description="Secret key for refresh tokens")
    jwt_access_expire_minutes: int = Field(default=15, alias="JWT_ACCESS_EXPIRE_MINUTES")
    jwt_refresh_expire_days: int = Field(default=30, alias="JWT_REFRESH_EXPIRE_DAYS")

    # Google OAuth
    google_client_id: str = Field(default="", alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(
        default="http://localhost:8000/auth/google/callback",
        alias="GOOGLE_REDIRECT_URI"
    )

    # Email (Resend)
    resend_api_key: str = Field(default="", alias="RESEND_API_KEY")
    email_from: str = Field(default="noreply@docmind.ai", alias="EMAIL_FROM")
    frontend_url: str = Field(default="http://localhost:3000", alias="FRONTEND_URL")

    # File upload limits
    max_pdf_size_mb: int = Field(default=50, alias="MAX_PDF_SIZE_MB")
    max_pdf_pages: int = Field(default=200, alias="MAX_PDF_PAGES")
    upload_dir: Path = Field(default=PROJECT_ROOT / "data" / "raw", alias="UPLOAD_DIR")

    # Rate limiting
    rate_limit_auth: str = Field(default="5/minute", alias="RATE_LIMIT_AUTH")
    rate_limit_upload: str = Field(default="10/hour", alias="RATE_LIMIT_UPLOAD")

    def ensure_data_dirs(self) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    def get_celery_broker_url(self) -> str:
        """
        Get Celery broker URL.

        Priority:
        1. CELERY_BROKER_URL env var (explicit)
        2. REDIS_URL env var (fallback to Redis)
        3. In-memory broker for testing (memory://)
        """
        if self.celery_broker_url:
            return self.celery_broker_url
        if self.redis_url:
            return self.redis_url
        return "memory://"

    def get_celery_result_backend(self) -> str:
        """
        Get Celery result backend URL.

        Priority:
        1. CELERY_RESULT_BACKEND env var (explicit)
        2. REDIS_URL env var (fallback to Redis)
        3. In-memory backend for testing (cache+memory://)
        """
        if self.celery_result_backend:
            return self.celery_result_backend
        if self.redis_url:
            return self.redis_url
        return "cache+memory://"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_data_dirs()
    return settings
