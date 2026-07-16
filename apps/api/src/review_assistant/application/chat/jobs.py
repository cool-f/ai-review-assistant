"""Connection-independent chat generation jobs.

An HTTP disconnect ends only one SSE subscription. The model call continues in
an application task. A reconnect with the same idempotency key receives a
content snapshot and follows the same task, so it never starts a second call.
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from typing import AsyncIterator

from review_assistant.application.chat.service import ChatService, _sse_event
from review_assistant.infrastructure.persistence.database import async_session_factory


@dataclass
class ChatStreamJob:
    session_id: str
    content_hash: str
    events: list[str] = field(default_factory=list)
    content: str = ""
    terminal_event: str | None = None
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task | None = None

    async def publish(self, raw_event: str) -> None:
        event = _parse_sse(raw_event)
        async with self.condition:
            if event.get("type") == "chunk":
                chunk = str(event.get("content") or "")
                self.content += chunk
                self.events.append(raw_event)
            elif event.get("type") == "replace":
                self.content = str(event.get("content") or "")
                self.events.append(raw_event)
            elif event.get("type") in {"done", "error"}:
                self.terminal_event = raw_event
            self.condition.notify_all()

    async def subscribe(self) -> AsyncIterator[str]:
        async with self.condition:
            next_event = len(self.events)
            snapshot = self.content
            terminal = self.terminal_event

        if snapshot:
            yield _sse_event({"type": "replace", "content": snapshot})
        if terminal is not None:
            yield terminal
            return

        while True:
            async with self.condition:
                await self.condition.wait_for(
                    lambda: len(self.events) > next_event
                    or self.terminal_event is not None
                )
                pending = self.events[next_event:]
                next_event = len(self.events)
                terminal = self.terminal_event
            for event in pending:
                yield event
            if terminal is not None:
                yield terminal
                return


_jobs: dict[str, ChatStreamJob] = {}
_jobs_lock = asyncio.Lock()


async def get_or_start_chat_job(
    *, session_id: str, content: str, idempotency_key: str
) -> ChatStreamJob:
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    async with _jobs_lock:
        existing = _jobs.get(idempotency_key)
        if existing is not None:
            if (
                existing.session_id != session_id
                or existing.content_hash != content_hash
            ):
                conflict = ChatStreamJob(session_id, content_hash)
                await conflict.publish(
                    _sse_event({
                        "type": "error",
                        "message": "Idempotency key is already used by another message.",
                    })
                )
                return conflict
            return existing

        job = ChatStreamJob(session_id, content_hash)
        _jobs[idempotency_key] = job
        job.task = asyncio.create_task(
            _run_chat_job(job, content, idempotency_key),
            name=f"chat:{idempotency_key}",
        )
        return job


async def _run_chat_job(
    job: ChatStreamJob, content: str, idempotency_key: str
) -> None:
    try:
        async with async_session_factory() as db:
            service = ChatService(db)
            async for event in service.stream_chat(
                job.session_id, content, idempotency_key
            ):
                await job.publish(event)
    except asyncio.CancelledError:
        raise
    except Exception:
        await job.publish(
            _sse_event({"type": "error", "message": "Internal server error."})
        )
    finally:
        if job.terminal_event is None:
            await job.publish(
                _sse_event({
                    "type": "error",
                    "message": "Generation did not complete normally.",
                })
            )
        asyncio.create_task(_expire_job(idempotency_key, job))


async def _expire_job(idempotency_key: str, job: ChatStreamJob) -> None:
    await asyncio.sleep(300)
    async with _jobs_lock:
        if _jobs.get(idempotency_key) is job:
            _jobs.pop(idempotency_key, None)


async def stop_chat_jobs() -> None:
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
