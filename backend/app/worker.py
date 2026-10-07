"""Celery worker entry point for every queue:
celery -A app.worker worker -Q ingestion,evaluation"""

import app.evaluation.tasks  # noqa: F401  (registers evaluation tasks)
from app.ingestion.tasks import celery_app

__all__ = ["celery_app"]
