"""
Celery application configuration (U3).

Configures Celery with Redis broker for background enrichment tasks.
Supports environment-driven configuration with fallback to in-memory broker for testing.

Configuration:
- Broker: Redis (default) or in-memory for testing
- Result backend: Redis or in-memory
- Serializer: JSON for portability
- Task time limits and retries
"""

from celery import Celery
from celery.signals import task_failure

from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def create_celery_app() -> Celery:
    """
    Create and configure Celery application.

    Configuration sources (in priority order):
    1. REDIS_URL environment variable (broker and result backend)
    2. CELERY_BROKER_URL / CELERY_RESULT_BACKEND (explicit overrides)
    3. In-memory broker/backend (fallback for testing)

    Returns:
        Configured Celery application instance
    """
    settings = get_settings()

    app = Celery("rag_pipeline")

    # Broker and result backend
    broker_url = settings.get_celery_broker_url()
    result_backend = settings.get_celery_result_backend()

    app.conf.broker_url = broker_url
    app.conf.result_backend = result_backend

    logger.info(
        "Celery broker: %s, result_backend: %s",
        broker_url[:20] + "***" if len(broker_url) > 20 else broker_url,
        result_backend[:20] + "***" if len(result_backend) > 20 else result_backend,
    )

    # Serialization
    app.conf.task_serializer = "json"
    app.conf.accept_content = ["json"]
    app.conf.result_serializer = "json"
    app.conf.timezone = "UTC"
    app.conf.enable_utc = True

    # Task configuration
    app.conf.task_track_started = True
    app.conf.task_time_limit = 3600  # 1 hour hard limit
    app.conf.task_soft_time_limit = 3300  # 55 minutes soft limit

    # Eager execution for testing (if enabled via settings)
    if settings.celery_task_always_eager:
        app.conf.task_always_eager = True
        app.conf.task_eager_propagates = True
        logger.info("Celery eager mode enabled (synchronous execution for testing)")

    # Result backend expiration (default: 1 hour)
    app.conf.result_expires = 3600

    # Register handlers
    _register_task_handlers(app)

    return app


def _register_task_handlers(app: Celery) -> None:
    """Register Celery signal handlers for monitoring and error handling."""

    @task_failure.connect(sender=app)
    def handle_task_failure(sender, task_id, exception, args, kwargs, traceback, **kw):
        """Log task failures."""
        logger.error(
            "Task failed: task_id=%s, exception=%s, traceback=%s",
            task_id,
            str(exception),
            traceback,
        )


# Global Celery application instance
_celery_app: Celery | None = None


def get_celery_app() -> Celery:
    """
    Get or create global Celery application instance.

    Uses singleton pattern: first call creates app, subsequent calls return same instance.
    Safe for imports across the application.

    Returns:
        Celery application instance
    """
    global _celery_app
    if _celery_app is None:
        _celery_app = create_celery_app()
    return _celery_app
