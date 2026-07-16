import asyncio

from review_assistant.application.homework.concurrency import (
    cancel_and_wait,
    drain_until_sentinel,
    interrupted_homework_status,
)


def test_one_sentinel_completes_a_multi_question_batch() -> None:
    async def scenario() -> list[str]:
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        await queue.put("question-1")
        await queue.put("question-2")
        await queue.put(None)
        return [event async for event in drain_until_sentinel(queue)]

    assert asyncio.run(scenario()) == ["question-1", "question-2"]


def test_cancel_waits_for_solver_cleanup_before_status_reconciliation() -> None:
    async def scenario() -> bool:
        cleaned_up = False

        async def solver():
            nonlocal cleaned_up
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                cleaned_up = True

        task = asyncio.create_task(solver())
        await asyncio.sleep(0)
        await cancel_and_wait([task])
        return cleaned_up

    assert asyncio.run(scenario()) is True


def test_interrupted_homework_state_reflects_durable_answer_count() -> None:
    assert interrupted_homework_status(total=3, answered=0) == "failed"
    assert interrupted_homework_status(total=3, answered=1) == "partial"
    assert interrupted_homework_status(total=3, answered=3) == "completed"
