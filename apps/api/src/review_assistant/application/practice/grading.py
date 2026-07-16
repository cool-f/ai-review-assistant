import json
import re
from dataclasses import dataclass

from review_assistant.infrastructure.ai.client import AbstractAIClient, get_ai_client


@dataclass(frozen=True, slots=True)
class GradingResult:
    correct: bool
    feedback: str
    method: str


def _normalize(value: str) -> str:
    return re.sub(r"[\s。．.!！,，;；]+$", "", value.strip().casefold())


def _choice_letter(value: str) -> str | None:
    match = re.match(r"^\s*([a-h])(?:[.、:：)）\s]|$)", value, re.IGNORECASE)
    return match.group(1).upper() if match else None


def deterministic_grade(question_type: str, submitted: str, expected: str) -> bool | None:
    if question_type == "选择题":
        submitted_letter = _choice_letter(submitted)
        expected_letter = _choice_letter(expected)
        if submitted_letter and expected_letter:
            return submitted_letter == expected_letter
        return _normalize(submitted) == _normalize(expected)
    if question_type == "填空题":
        return _normalize(submitted) == _normalize(expected)
    return None


class GradingService:
    def __init__(self, ai_client: AbstractAIClient | None = None):
        self._ai_client = ai_client

    @property
    def ai_client(self) -> AbstractAIClient:
        if self._ai_client is None:
            self._ai_client = get_ai_client()
        return self._ai_client

    async def grade(
        self, *, question_type: str, question: str, submitted: str, expected: str
    ) -> GradingResult:
        deterministic = deterministic_grade(question_type, submitted, expected)
        if deterministic is not None:
            return GradingResult(
                correct=deterministic,
                feedback="回答正确" if deterministic else f"回答不正确，参考答案：{expected}",
                method="deterministic",
            )

        response = await self.ai_client.chat(
            [
                {"role": "system", "content": "你是严谨的判题器，只输出 JSON：{\"correct\":bool,\"feedback\":string}。"},
                {"role": "user", "content": f"题目：{question}\n参考答案：{expected}\n学生答案：{submitted}"},
            ],
            temperature=0,
        )
        content = response.content.strip()
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            raise ValueError("AI 判题返回格式无效")
        parsed = json.loads(match.group(0))
        correct = parsed.get("correct")
        if not isinstance(correct, bool):
            raise ValueError("AI 判题的 correct 字段必须是布尔值")
        return GradingResult(
            correct=correct,
            feedback=str(parsed.get("feedback") or "已完成判题"),
            method="ai",
        )
