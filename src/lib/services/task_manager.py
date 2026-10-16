from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class TaskState:
    status: str
    link: str
    error: str | None = None
    owner: str | None = None
    # Objeto de la imagen de origen (predicciones), para que /status pueda devolver su URL
    source: str | None = None


class TaskManager:
    def __init__(self) -> None:
        self.jobs: dict[str, TaskState] = {}

    def create_job(self, owner: str | None = None, source: str | None = None) -> str:
        job_id = str(uuid4())
        self.jobs[job_id] = TaskState(status="inProgress", link="none", owner=owner, source=source)
        return job_id

    async def run_job(self, job_id: str, coroutine) -> None:
        owner, source = self.jobs[job_id].owner, self.jobs[job_id].source
        try:
            result_link = await coroutine
            self.jobs[job_id] = TaskState(status="done", link=result_link, owner=owner, source=source)
        except Exception as exc:
            logger.exception("Background job %s failed", job_id)
            self.jobs[job_id] = TaskState(
                status="failed",
                link="none",
                error=f"{type(exc).__name__}: {exc}",
                owner=owner,
                source=source,
            )

    def schedule(self, job_id: str, coroutine) -> None:
        asyncio.create_task(self.run_job(job_id, coroutine))

    def get(self, job_id: str) -> TaskState | None:
        return self.jobs.get(job_id)
