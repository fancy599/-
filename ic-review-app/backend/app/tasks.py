"""Optional Celery entrypoint. The web app remains runnable without Celery."""
from __future__ import annotations

from celery import Celery

from app.config import get_settings

settings = get_settings()
celery_app = Celery("ic_review", broker=settings.redis_url, backend=settings.redis_url)


@celery_app.task(name="ic_review.run_pipeline")
def run_pipeline_task(task_id: int, from_step: int = 1, mode: str = "hybrid") -> None:
    from app.api.routes import _run_pipeline_thread

    _run_pipeline_thread(task_id, from_step, mode)
