"""Connection-independent homework solve jobs with replayable SSE events."""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator

from review_assistant.application.homework.service import HomeworkService, _sse_event
from review_assistant.infrastructure.persistence.database import async_session_factory


logger = logging.getLogger(__name__)


@dataclass
class HomeworkSolveJob:
    homework_id: str
    events: list[str] = field(default_factory=list)
    terminal: bool = False
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task | None = None

    async def publish(self, raw_event: str) -> None:
        payload = _parse_sse(raw_event)
        async with self.condition:
            self.events.append(raw_event)
            if payload.get("type") in {"done", "error"}:
                self.terminal = True
            self.condition.notify_all()

    async def subscribe(self) -> AsyncIterator[str]:
        next_event = 0
        while True:
            async with self.condition:
                pending = self.events[next_event:]
                next_event = len(self.events)
                terminal = self.terminal
            for event in pending:
                yield event
            if terminal:
                return
            async with self.condition:
                await self.condition.wait_for(
                    lambda: len(self.events) > next_event or self.terminal
                )


_jobs: dict[str, HomeworkSolveJob] = {}
_jobs_lock = asyncio.Lock()


async def get_homework_job(homework_id: str) -> HomeworkSolveJob | None:
    async with _jobs_lock:
        return _jobs.get(homework_id)


def should_replay_homework_job(job: HomeworkSolveJob, homework_status: str) -> bool:
    """Reconnect to active/completed work; allow failed or partial work to retry now."""
    return not job.terminal or homework_status == "completed"


async def discard_terminal_homework_job(
    homework_id: str, job: HomeworkSolveJob
) -> None:
    async with _jobs_lock:
        if job.terminal and _jobs.get(homework_id) is job:
            _jobs.pop(homework_id, None)


async def start_homework_job(homework_id: str) -> HomeworkSolveJob:
    """Start the solve task now, independently of StreamingResponse iteration."""
    async with _jobs_lock:
        existing = _jobs.get(homework_id)
        if existing is not None:
            return existing
        job = HomeworkSolveJob(homework_id)
        _jobs[homework_id] = job
        job.task = asyncio.create_task(
            _run_homework_job(job), name=f"homework:{homework_id}"
        )
        return job


async def _run_homework_job(job: HomeworkSolveJob) -> None:
    service: HomeworkService | None = None
    try:
        async with async_session_factory() as db:
            service = HomeworkService(db)
            async for event in service.batch_solve(job.homework_id):
                await job.publish(event)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Homework solve job failed: %s", job.homework_id)
        await job.publish(
            _sse_event({"type": "error", "message": "Homework solve job failed."})
        )
    finally:
        completed = bool(
            job.events and _parse_sse(job.events[-1]).get("type") == "done"
        )
        if service is not None and not completed:
            try:
                await asyncio.shield(
                    service.reconcile_interrupted_homework(job.homework_id)
                )
            except Exception:
                logger.exception(
                    "Homework status reconciliation failed: %s", job.homework_id
                )
        if not job.terminal:
            await job.publish(
                _sse_event({"type": "error", "message": "Homework solve was interrupted."})
            )
        asyncio.create_task(_expire_job(job.homework_id, job))


async def _expire_job(homework_id: str, job: HomeworkSolveJob) -> None:
    await asyncio.sleep(300)
    async with _jobs_lock:
        if _jobs.get(homework_id) is job:
            _jobs.pop(homework_id, None)


async def stop_homework_jobs() -> None:
    async with _jobs_lock:
        tasks = [
            job.task
            for job in _jobs.values()
            if job.task is not None and not job.task.done()
        ]
        _jobs.clear()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _parse_sse(raw_event: str) -> dict:
    for line in raw_event.splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except json.JSONDecodeError:
                return {}
    return {}
