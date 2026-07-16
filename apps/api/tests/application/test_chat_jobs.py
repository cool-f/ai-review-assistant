import asyncio
import json

from review_assistant.application.chat import jobs
from review_assistant.application.chat.jobs import ChatStreamJob
from review_assistant.application.chat.service import _sse_event


def _payload(raw: str) -> dict:
    return json.loads(raw.split("data: ", 1)[1])


def test_reconnect_receives_snapshot_then_only_new_chunks() -> None:
    async def run():
        job = ChatStreamJob("session-1", "hash")
        await job.publish(_sse_event({"type": "chunk", "content": "first"}))
        subscription = job.subscribe()
        snapshot = await anext(subscription)
        await job.publish(_sse_event({"type": "chunk", "content": " second"}))
        new_chunk = await anext(subscription)
        await job.publish(_sse_event({"type": "done", "message_id": "m-1", "token_count": 2}))
        done = await anext(subscription)
        return snapshot, new_chunk, done

    snapshot, new_chunk, done = asyncio.run(run())

    assert _payload(snapshot) == {"type": "replace", "content": "first"}
    assert _payload(new_chunk) == {"type": "chunk", "content": " second"}
    assert _payload(done)["type"] == "done"


def test_active_subscriber_receives_replace_replay_before_done() -> None:
    async def run():
        job = ChatStreamJob("session-replay", "hash")
        subscription = job.subscribe()
        waiting = asyncio.create_task(anext(subscription))
        await asyncio.sleep(0)
        await job.publish(_sse_event({"type": "replace", "content": "saved answer"}))
        replay = await waiting
        await job.publish(_sse_event({"type": "done", "message_id": "m-saved"}))
        done = await anext(subscription)
        return replay, done

    replay, done = asyncio.run(run())

    assert _payload(replay) == {"type": "replace", "content": "saved answer"}
    assert _payload(done)["type"] == "done"


def test_same_idempotency_key_reuses_one_generation_task(monkeypatch) -> None:
    async def run() -> tuple[bool, int]:
        started = 0
        release = asyncio.Event()

        async def fake_run(job, content, idempotency_key):
            nonlocal started
            started += 1
            await release.wait()
            await job.publish(_sse_event({"type": "done", "message_id": "m-1"}))

        monkeypatch.setattr(jobs, "_run_chat_job", fake_run)
        first = await jobs.get_or_start_chat_job(
            session_id="session-2", content="same message", idempotency_key="key-reconnect"
        )
        second = await jobs.get_or_start_chat_job(
            session_id="session-2", content="same message", idempotency_key="key-reconnect"
        )
        await asyncio.sleep(0)
        release.set()
        assert first.task is not None
        await first.task
        await jobs.stop_chat_jobs()
        return first is second, started

    same_job, started = asyncio.run(run())

    assert same_job is True
    assert started == 1
