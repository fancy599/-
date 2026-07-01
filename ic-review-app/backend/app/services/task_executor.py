"""Pluggable task submission with a safe local fallback."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from app.config import get_settings


@dataclass
class Submission:
    backend: str
    degraded: bool = False
    notice: str = ""


def submit_pipeline(local_runner: Callable[..., None], task_id: int, from_step: int, mode: str) -> Submission:
    settings = get_settings()
    requested = settings.task_executor.strip().lower()
    if requested == "celery":
        try:
            from redis import Redis
            from app.tasks import celery_app

            Redis.from_url(
                settings.redis_url,
                socket_connect_timeout=1,
                socket_timeout=1,
            ).ping()
            celery_app.send_task("ic_review.run_pipeline", args=[task_id, from_step, mode])
            return Submission(backend="celery")
        except Exception as exc:
            notice = f"Celery/Redis 暂不可用，已自动降级为本地执行器：{type(exc).__name__}"
            thread = threading.Thread(
                target=local_runner, args=(task_id, from_step, mode), daemon=True
            )
            thread.start()
            return Submission(backend="local_thread", degraded=True, notice=notice)

    thread = threading.Thread(target=local_runner, args=(task_id, from_step, mode), daemon=True)
    thread.start()
    return Submission(backend="local_thread")
