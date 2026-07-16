import asyncio

from review_assistant.infrastructure.ai.client import (
    AIResponse,
    AbstractAIClient,
    MeteredAIClient,
)
from review_assistant.infrastructure.usage.context import usage_scope
from review_assistant.infrastructure.usage import token_counter


class FakeOpenAIClient(AbstractAIClient):
    def __init__(self):
        super().__init__(api_key="test", model="test-model")

    async def chat(self, messages: list[dict], **kwargs) -> AIResponse:
        return AIResponse(
            content="answer",
            usage={"prompt_tokens": 11, "completion_tokens": 7},
        )

    async def chat_stream(self, messages: list[dict], **kwargs):
        yield "streamed "
        yield "answer"


def test_metered_chat_enforces_budget_and_records_business_context(monkeypatch):
    budget_checks = 0
    records: list[dict] = []

    async def ensure_budget() -> None:
        nonlocal budget_checks
        budget_checks += 1

    async def record_usage(**kwargs) -> None:
        records.append(kwargs)

    monkeypatch.setattr(token_counter, "ensure_budget", ensure_budget)
    monkeypatch.setattr(token_counter, "record_usage", record_usage)

    async def run():
        client = MeteredAIClient(FakeOpenAIClient())
        with usage_scope("practice_grading", course_id="course-1", session_id="session-1"):
            return await client.chat([{"role": "user", "content": "question"}])

    response = asyncio.run(run())

    assert response.content == "answer"
    assert budget_checks == 1
    assert records == [{
        "provider": "openai",
        "model": "test-model",
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "session_id": "session-1",
        "course_id": "course-1",
        "purpose": "practice_grading",
    }]


def test_metered_stream_records_once_when_consumer_finishes(monkeypatch):
    records: list[dict] = []

    async def ensure_budget() -> None:
        return None

    async def record_usage(**kwargs) -> None:
        records.append(kwargs)

    monkeypatch.setattr(token_counter, "ensure_budget", ensure_budget)
    monkeypatch.setattr(token_counter, "record_usage", record_usage)

    async def run() -> str:
        client = MeteredAIClient(FakeOpenAIClient())
        with usage_scope("chat", course_id="course-1"):
            return "".join([
                chunk async for chunk in client.chat_stream(
                    [{"role": "user", "content": "question"}]
                )
            ])

    assert asyncio.run(run()) == "streamed answer"
    assert len(records) == 1
    assert records[0]["purpose"] == "chat"
    assert records[0]["course_id"] == "course-1"
    assert records[0]["completion_tokens"] > 0
