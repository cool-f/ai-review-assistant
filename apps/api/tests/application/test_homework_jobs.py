import asyncio
import json

from review_assistant.application.homework import jobs
from review_assistant.application.homework.jobs import (
    HomeworkSolveJob,
    should_replay_homework_job,
)
from review_assistant.application.homework.service import _sse_event


def _payload(raw: str) -> dict:
    return json.loads(raw.split("data: ", 1)[1])


def test_homework_job_replays_events_that_arrive_before_subscription() -> None:
    async def run():
        job = HomeworkSolveJob("homework-replay")
        await job.publish(_sse_event({"type": "token", "content": "answer"}))
        await job.publish(_sse_event({"type": "done", "solved_count": 1}))
        return [_payload(event) async for event in job.subscribe()]

    events = asyncio.run(run())

    assert [event["type"] for event in events] == ["token", "done"]


def test_start_homework_job_runs_before_any_sse_subscription(monkeypatch) -> None:
    async def run() -> bool:
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_runner(job):
            started.set()
            await release.wait()

        monkeypatch.setattr(jobs, "_run_homework_job", fake_runner)
        job = await jobs.start_homework_job("homework-start-immediately")
        await asyncio.wait_for(started.wait(), timeout=1)
        ran_without_subscriber = started.is_set()
        release.set()
        assert job.task is not None
        await job.task
        await jobs.stop_homework_jobs()
        return ran_without_subscriber

    assert asyncio.run(run()) is True


def test_partial_terminal_job_can_be_replaced_immediately(monkeypatch) -> None:
    async def run() -> bool:
        release = asyncio.Event()

        async def fake_runner(job):
            await release.wait()

        monkeypatch.setattr(jobs, "_run_homework_job", fake_runner)
        old_job = HomeworkSolveJob("homework-retry")
        await old_job.publish(_sse_event({"type": "done", "solved_count": 1}))

        assert should_replay_homework_job(old_job, "completed") is True
        assert should_replay_homework_job(old_job, "partial") is False
        assert should_replay_homework_job(old_job, "failed") is False

        async with jobs._jobs_lock:
            jobs._jobs[old_job.homework_id] = old_job
        await jobs.discard_terminal_homework_job(old_job.homework_id, old_job)
        new_job = await jobs.start_homework_job(old_job.homework_id)
        replaced = new_job is not old_job and new_job.task is not None
        release.set()
        await new_job.task
        await jobs.stop_homework_jobs()
        return replaced

    assert asyncio.run(run()) is True
