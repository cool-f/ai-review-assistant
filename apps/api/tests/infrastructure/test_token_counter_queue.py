import asyncio

from review_assistant.infrastructure.usage import token_counter


def test_saturated_usage_queue_applies_backpressure_without_losing_record(monkeypatch) -> None:
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1)
    monkeypatch.setattr(token_counter, "_queue", queue)
    monkeypatch.setattr(token_counter, "_pending_tokens", 0)

    async def run():
        await token_counter.record_usage("openai", "m", 2, 1, purpose="chat")
        waiting = asyncio.create_task(
            token_counter.record_usage(
                "openai", "m", 4, 3, course_id="course-1", purpose="homework_solve"
            )
        )
        await asyncio.sleep(0)
        assert waiting.done() is False
        first = queue.get_nowait()
        await waiting
        second = queue.get_nowait()
        return first, second

    first, second = asyncio.run(run())

    assert first["purpose"] == "chat"
    assert second["purpose"] == "homework_solve"
    assert second["course_id"] == "course-1"
    assert token_counter._pending_tokens == 10
