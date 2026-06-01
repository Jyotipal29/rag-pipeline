from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from app.api.routes.ask import router as ask_router
from app.api.routes.ingestion import router as ingestion_router
from app.config.settings import get_settings
from app.metrics.enrichment_metrics import get_metrics
from app.retrieval import keyword_index
from app.utils.logger import configure_root_logging, get_logger
from app.vectorstore.qdrant_client import (
    close_qdrant_client,
    ensure_collection,
    iter_all_chunks,
)

load_dotenv()

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_root_logging(settings.log_level)
    settings.ensure_data_dirs()

    # Initialize metrics
    metrics = get_metrics()
    logger.info("Enrichment metrics initialized")

    try:
        ensure_collection()
        keyword_index.rebuild_keyword_index(iter_all_chunks())
        logger.info("Qdrant collection ready")
    except Exception as exc:
        logger.warning("Qdrant not available at startup (index/search will fail): %s", exc)

    yield

    # Log final metrics before shutdown
    logger.info("Logging final metrics before shutdown")
    metrics.log_stats()

    close_qdrant_client()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(ingestion_router)
    app.include_router(ask_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": settings.app_name}

    return app


app = create_app()
