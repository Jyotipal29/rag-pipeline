from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.ask import router as ask_router
from app.api.routes.ingestion import router as ingestion_router
from app.auth.router import router as auth_router
from app.config.settings import get_settings
from app.db.collections import create_indexes
from app.db.mongo import close_db, connect_db, get_db
from app.documents.router import router as documents_router
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

    # Initialize MongoDB
    try:
        await connect_db()
        db = await get_db()
        await create_indexes(db)
        logger.info("MongoDB initialized and indexes created")
    except Exception as exc:
        logger.warning("MongoDB not available at startup: %s", exc)

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
    await close_db()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:8000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(auth_router)
    app.include_router(documents_router)
    app.include_router(ingestion_router)
    app.include_router(ask_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": settings.app_name}

    return app


app = create_app()
