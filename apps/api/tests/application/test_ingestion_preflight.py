import asyncio

from review_assistant.application.ingestion.preflight import preflight_document
from review_assistant.application.ingestion.pipeline import plan_ingestion_retry


def test_homework_preflight_estimates_question_count_without_persisting() -> None:
    result = asyncio.run(preflight_document(
        filename="作业.txt",
        content="1. 第一题\n2. 第二题".encode(),
        file_type="txt",
        purpose="homework",
        provider="deepseek",
        model="test",
    ))
    assert result["readable"] is True
    assert result["estimated_questions"] == 2
    assert result["estimated_cost"]["total"] >= 0


def test_ingestion_retry_preserves_learning_data_unless_force_is_explicit() -> None:
    assert plan_ingestion_retry(
        force=False, status="partial", failed_stage="embedding", has_knowledge=True
    ) == "embedding"
    assert plan_ingestion_retry(
        force=False, status="partial", failed_stage="linking", has_knowledge=True
    ) == "linking"
    assert plan_ingestion_retry(
        force=False, status="failed", failed_stage="knowledge", has_knowledge=True
    ) == "force_required"
    assert plan_ingestion_retry(
        force=True, status="partial", failed_stage="embedding", has_knowledge=True
    ) == "full"
