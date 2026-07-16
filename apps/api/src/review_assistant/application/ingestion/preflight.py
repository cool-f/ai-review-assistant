import asyncio
import os
import tempfile
from pathlib import Path
from typing import Literal

from review_assistant.application.homework.service import HomeworkService
from review_assistant.infrastructure.documents.text_extractor import TextExtractor


_MODEL_PRICING: dict[str, dict[str, float]] = {
    "anthropic": {"input": 3.0, "output": 15.0},
    "openai": {"input": 2.5, "output": 10.0},
    "deepseek": {"input": 0.27, "output": 1.10},
    "qwen": {"input": 0.80, "output": 2.0},
}


def estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = _MODEL_PRICING.get(provider, {"input": 1.0, "output": 4.0}).copy()
    model_lower = (model or "").lower()
    if "flash" in model_lower or "mini" in model_lower:
        pricing = {key: value * 0.3 for key, value in pricing.items()}
    elif "opus" in model_lower or "pro" in model_lower:
        pricing = {key: value * 1.5 for key, value in pricing.items()}
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


async def preflight_document(
    *,
    filename: str,
    content: bytes,
    file_type: str,
    purpose: Literal["courseware", "homework"],
    provider: str,
    model: str,
) -> dict:
    """Inspect a document without persisting it or starting paid AI work."""
    suffix = Path(filename).suffix.lower()
    temp_path: str | None = None
    try:
        handle, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(handle)
        Path(temp_path).write_bytes(content)
        text, page_count = await asyncio.to_thread(TextExtractor.extract, temp_path, file_type)
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)

    stripped = (text or "").strip()
    if not stripped:
        return {
            "readable": False,
            "filename": filename,
            "file_type": file_type,
            "file_size_bytes": len(content),
            "page_count": page_count,
            "estimated_knowledge_points": 0,
            "estimated_questions": 0,
            "estimated_cost": {
                "extraction": 0.0, "embedding": 0.0, "total": 0.0,
                "currency": "USD", "note": "无法从文件中提取到文本内容，请确认文件是否损坏",
            },
            "provider": provider,
            "model": model or "默认",
        }

    input_tokens = max(1, int(len(stripped) / 2.8))
    if purpose == "homework":
        question_count = len(HomeworkService.extract_questions(stripped))
        output_tokens = max(1, question_count) * 800
        extraction_cost = 0.0
        embedding_cost = 0.0
        note = "费用主要来自确认后逐题 AI 解答；实际费用会随题目难度变化"
        kp_count = 0
    else:
        kp_count = max(1, len(stripped) // 1500)
        question_count = 0
        output_tokens = kp_count * 400
        extraction_cost = estimate_cost(provider, model, input_tokens, output_tokens)
        embedding_cost = round(max(1, len(stripped) // 2000) * 0.00002, 4)
        note = "实际费用可能因模型和用量而异，此仅为估算"

    ai_cost = estimate_cost(provider, model, input_tokens, output_tokens)
    total = ai_cost + embedding_cost
    return {
        "readable": True,
        "suggested_mode": None,
        "filename": filename,
        "file_type": file_type,
        "file_size_bytes": len(content),
        "page_count": page_count,
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_total_tokens": input_tokens + output_tokens,
        "estimated_knowledge_points": kp_count,
        "estimated_questions": question_count,
        "estimated_cost": {
            "extraction": round(extraction_cost if purpose == "courseware" else ai_cost, 4),
            "embedding": embedding_cost,
            "total": round(total, 4),
            "currency": "USD",
            "note": note,
        },
        "provider": provider,
        "model": model or "默认",
    }
