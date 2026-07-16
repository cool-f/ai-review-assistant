import asyncio

import pytest

from review_assistant.application.practice.grading import GradingService, deterministic_grade
from review_assistant.infrastructure.ai.client import AIResponse, AbstractAIClient


class _StringBooleanClient(AbstractAIClient):
    def __init__(self):
        super().__init__(api_key="test", model="test")

    async def chat(self, messages, **kwargs):
        return AIResponse(content='{"correct":"false","feedback":"wrong type"}')

    async def chat_stream(self, messages, **kwargs):
        if False:
            yield ""


def test_choice_answer_accepts_option_letter_or_full_option() -> None:
    assert deterministic_grade("选择题", "A", "A. 光合作用") is True
    assert deterministic_grade("选择题", "B. 呼吸作用", "A. 光合作用") is False


def test_fill_answer_ignores_whitespace_and_terminal_punctuation() -> None:
    assert deterministic_grade("填空题", "  牛顿第二定律。 ", "牛顿第二定律") is True


def test_open_question_defers_to_ai_grader() -> None:
    assert deterministic_grade("证明题", "证明过程", "标准证明") is None


def test_ai_grader_rejects_string_boolean_instead_of_marking_it_true() -> None:
    service = GradingService(ai_client=_StringBooleanClient())

    with pytest.raises(ValueError, match="布尔值"):
        asyncio.run(service.grade(
            question_type="证明题",
            question="prove it",
            submitted="attempt",
            expected="reference",
        ))
