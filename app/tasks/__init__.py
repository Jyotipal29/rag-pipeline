"""
Background task definitions for the RAG pipeline (U3).

Provides Celery task implementations for asynchronous processing:
- enrichment_tasks: Background enrichment of documents

Tasks are defined in submodules and automatically registered with Celery.
"""

from app.config.celery import get_celery_app

# Import task definitions to register with Celery
from app.tasks.enrichment_tasks import enrich_document_task

__all__ = ["enrich_document_task", "get_celery_app"]
