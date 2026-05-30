from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from app.api.routes.ingestion import router as ingestion_router
from app.config.settings import get_settings
from app.utils.logger import configure_root_logging, get_logger
from app.vectorstore.qdrant_client import close_qdrant_client, ensure_collection

load_dotenv()

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_root_logging(settings.log_level)
    settings.ensure_data_dirs()

    try:
        ensure_collection()
        logger.info("Qdrant collection ready")
    except Exception as exc:
        logger.warning("Qdrant not available at startup (index/search will fail): %s", exc)

    yield
    close_qdrant_client()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(ingestion_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": settings.app_name}

    return app


app = create_app()
