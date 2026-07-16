"""
Token 用量监控服务

提供:
  - record_usage()       — 异步队列背压写入，饱和时不丢审计记录
  - get_daily_usage()    — 按天聚合查询
  - get_usage_by_provider() — 按提供商分组查询
  - check_budget()       — 预算检查（warnings 不阻塞）
  - cleanup_old_records() — 90 天自动清理

架构:
  record_usage() ──> asyncio.Queue ──> _worker (后台 task) ──> DB 批量写入
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, func, delete

from review_assistant.infrastructure.persistence.database import async_session_factory
from review_assistant.infrastructure.persistence.models import TokenUsageLog
from review_assistant.domain.budget import BudgetState

logger = logging.getLogger(__name__)

# ── 全局队列与 worker ────────────────────────────────
_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=10000)
_worker_task: Optional[asyncio.Task] = None
_shutdown_event = asyncio.Event()
_cleanup_task: Optional[asyncio.Task] = None
_pending_tokens = 0

BATCH_SIZE = 100       # 累积多少条后批量落库
FLUSH_INTERVAL = 1.0   # 最长等待秒数后落库


# ═══════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════

ALLOWED_PROVIDERS: set[str] = {"anthropic", "openai", "qwen", "deepseek", "dashscope"}
_TOKEN_PRICES = {
    "anthropic": (3.0, 15.0), "openai": (2.5, 10.0),
    "qwen": (0.8, 2.0), "deepseek": (0.27, 1.1), "dashscope": (0.02, 0.0),
}


async def record_usage(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    session_id: Optional[str] = None,
    course_id: Optional[str] = None,
    purpose: str = "unspecified",
    estimated_cost_usd: float = 0.0,
) -> None:
    """
    记录一次 AI 调用 Token 用量（写入异步队列；饱和时等待可用槽位）

    Args:
        provider:          提供商 (anthropic | openai | qwen | deepseek)
        model:             模型名称
        prompt_tokens:     输入 Token 数
        completion_tokens: 输出 Token 数
        session_id:        关联的会话 ID，可为 None

    Raises:
        ValueError: prompt_tokens 或 completion_tokens 为负值时抛出
    """
    # ── 输入校验 ──────────────────────────────────
    if prompt_tokens < 0:
        raise ValueError(f"prompt_tokens must be >= 0, got {prompt_tokens}")
    if completion_tokens < 0:
        raise ValueError(f"completion_tokens must be >= 0, got {completion_tokens}")

    # provider 白名单校验，不在限定集合内则标记为 'unknown'
    if provider not in ALLOWED_PROVIDERS:
        logger.warning(
            "Unknown provider '%s' — marking as 'unknown'. "
            "Allowed providers: %s",
            provider, ", ".join(sorted(ALLOWED_PROVIDERS)),
        )
        provider = "unknown"

    if estimated_cost_usd <= 0:
        input_price, output_price = _TOKEN_PRICES.get(provider, (1.0, 4.0))
        estimated_cost_usd = (
            prompt_tokens * input_price + completion_tokens * output_price
        ) / 1_000_000

    record = {
        "provider": provider,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "session_id": session_id,
        "course_id": course_id,
        "purpose": purpose or "unspecified",
        "estimated_cost_usd": max(0.0, estimated_cost_usd),
    }
    record_tokens = prompt_tokens + completion_tokens
    global _pending_tokens
    _pending_tokens += record_tokens
    # Backpressure is intentional: once the durable-writer queue is saturated,
    # the paid call must not return before its audit record has a retained slot.
    # This preserves both budget accounting and business dimensions instead of
    # dropping the row on QueueFull.
    await asyncio.shield(_queue.put(record))


async def get_daily_usage(days: int = 7, course_id: str | None = None) -> list[dict]:
    """
    按天聚合最近 N 天的 Token 用量

    Args:
        days: 统计天数，默认 7

    Returns:
        [{"date": "2026-06-27", "prompt_tokens": N, "completion_tokens": N,
          "total_tokens": N, "call_count": N}, ...]
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with async_session_factory() as db:
        query = (
            select(
                func.date(TokenUsageLog.created_at).label("date"),
                func.sum(TokenUsageLog.prompt_tokens).label("total_prompt"),
                func.sum(TokenUsageLog.completion_tokens).label("total_completion"),
                func.count(TokenUsageLog.id).label("call_count"),
            )
            .where(TokenUsageLog.created_at >= cutoff)
            .group_by(func.date(TokenUsageLog.created_at))
            .order_by(func.date(TokenUsageLog.created_at).desc())
        )
        if course_id:
            query = query.where(TokenUsageLog.course_id == course_id)
        result = await db.execute(query)
        rows = result.all()

    return [
        {
            "date": str(row.date),
            "prompt_tokens": int(row.total_prompt or 0),
            "completion_tokens": int(row.total_completion or 0),
            "total_tokens": int(row.total_prompt or 0) + int(row.total_completion or 0),
            "call_count": row.call_count,
        }
        for row in rows
    ]


async def get_usage_by_provider(days: int = 7, course_id: str | None = None) -> list[dict]:
    """
    按提供商分组统计最近 N 天的 Token 用量

    Args:
        days: 统计天数，默认 7

    Returns:
        [{"provider": "openai", "prompt_tokens": N, "completion_tokens": N,
          "total_tokens": N, "call_count": N}, ...]
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with async_session_factory() as db:
        query = (
            select(
                TokenUsageLog.provider,
                func.sum(TokenUsageLog.prompt_tokens).label("total_prompt"),
                func.sum(TokenUsageLog.completion_tokens).label("total_completion"),
                func.count(TokenUsageLog.id).label("call_count"),
            )
            .where(TokenUsageLog.created_at >= cutoff)
            .group_by(TokenUsageLog.provider)
            .order_by(
                func.sum(
                    TokenUsageLog.prompt_tokens + TokenUsageLog.completion_tokens
                ).desc()
            )
        )
        if course_id:
            query = query.where(TokenUsageLog.course_id == course_id)
        result = await db.execute(query)
        rows = result.all()

    return [
        {
            "provider": row.provider,
            "prompt_tokens": int(row.total_prompt or 0),
            "completion_tokens": int(row.total_completion or 0),
            "total_tokens": int(row.total_prompt or 0) + int(row.total_completion or 0),
            "call_count": row.call_count,
        }
        for row in rows
    ]


async def get_usage_by_purpose(days: int = 7, course_id: str | None = None) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with async_session_factory() as db:
        query = (
            select(
                TokenUsageLog.purpose,
                func.sum(TokenUsageLog.prompt_tokens).label("total_prompt"),
                func.sum(TokenUsageLog.completion_tokens).label("total_completion"),
                func.sum(TokenUsageLog.estimated_cost_usd).label("cost"),
                func.count(TokenUsageLog.id).label("call_count"),
            )
            .where(TokenUsageLog.created_at >= cutoff)
            .group_by(TokenUsageLog.purpose)
            .order_by(func.sum(TokenUsageLog.prompt_tokens + TokenUsageLog.completion_tokens).desc())
        )
        if course_id:
            query = query.where(TokenUsageLog.course_id == course_id)
        rows = (await db.execute(query)).all()
    return [{
        "purpose": row.purpose,
        "prompt_tokens": int(row.total_prompt or 0),
        "completion_tokens": int(row.total_completion or 0),
        "total_tokens": int(row.total_prompt or 0) + int(row.total_completion or 0),
        "estimated_cost_usd": round(float(row.cost or 0), 6),
        "call_count": row.call_count,
    } for row in rows]


class BudgetExceededError(RuntimeError):
    pass


async def ensure_budget() -> None:
    state = await check_budget()
    if not state["within_budget"]:
        raise BudgetExceededError(state["warning"] or "今日 AI 用量预算已耗尽")


async def check_budget() -> dict:
    """
    检查今日用量是否超出每日预算

    Returns:
        {
            "today_usage": int,
            "daily_budget": int,
            "percentage": float,
            "within_budget": bool,
            "call_count_today": int,
            "warning": str | None,
        }
    """
    from review_assistant.core.config import get_settings

    settings = get_settings()
    budget = settings.DAILY_TOKEN_BUDGET

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    async with async_session_factory() as db:
        result = await db.execute(
            select(
                func.coalesce(
                    func.sum(
                        TokenUsageLog.prompt_tokens + TokenUsageLog.completion_tokens
                    ),
                    0,
                ),
                func.count(TokenUsageLog.id),
            ).where(TokenUsageLog.created_at >= today_start)
        )
        total_today, call_count = result.one()
        total_today = int(total_today) + _pending_tokens

    budget_state = BudgetState(total_today, budget)
    within_budget = budget_state.allows_ai_call
    percentage = budget_state.percentage

    warning: Optional[str] = None
    if budget > 0 and not within_budget:
        warning = (
            f"今日 Token 用量已超出预算上限 ({budget:,})，"
            f"当前用量: {total_today:,}"
        )
    elif budget > 0 and percentage >= 80:
        warning = (
            f"今日 Token 用量已达预算 {percentage}% "
            f"({total_today:,}/{budget:,})"
        )

    return {
        "today_usage": total_today,
        "daily_budget": budget,
        "percentage": percentage,
        "within_budget": within_budget,
        "call_count_today": call_count,
        "warning": warning,
    }


async def cleanup_old_records() -> int:
    """
    删除 90 天前的 Token 用量记录

    Returns:
        删除的行数
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)

    try:
        async with async_session_factory() as db:
            result = await db.execute(
                delete(TokenUsageLog).where(TokenUsageLog.created_at < cutoff)
            )
            await db.commit()
            deleted = result.rowcount
            if deleted:
                logger.info("Cleaned up %d old token usage records (>90 days)", deleted)
            return deleted
    except Exception:
        logger.exception("Failed to clean up old token usage records")
        return 0


# ═══════════════════════════════════════════════════════
# Worker 生命周期管理
# ═══════════════════════════════════════════════════════

async def _worker() -> None:
    """后台 worker：从队列消费记录，批量写入数据库"""
    batch: list[dict] = []

    while not _shutdown_event.is_set():
        try:
            record = await asyncio.wait_for(_queue.get(), timeout=FLUSH_INTERVAL)
            batch.append(record)

            # 尽可能一次多取几条（非阻塞）
            while len(batch) < BATCH_SIZE:
                try:
                    batch.append(_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            if len(batch) >= BATCH_SIZE:
                if await _flush_batch(batch):
                    batch.clear()
                else:
                    await asyncio.sleep(1.0)

        except asyncio.TimeoutError:
            if batch:
                if await _flush_batch(batch):
                    batch.clear()
                else:
                    await asyncio.sleep(1.0)

    # ── 关闭前排空剩余记录 ──────────────────────────
    remaining: list[dict] = list(batch)
    while True:
        try:
            remaining.append(_queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    if remaining:
        for attempt in range(5):
            if await _flush_batch(remaining):
                logger.info("Flushed %d remaining token records on shutdown", len(remaining))
                remaining.clear()
                break
            await asyncio.sleep(min(2 ** attempt, 8))
        if remaining:
            logger.critical(
                "Unable to persist %d token usage records during shutdown; "
                "their tokens remain reserved for this process lifetime",
                len(remaining),
            )

    logger.info("TokenCounter worker shut down gracefully")


async def _flush_batch(batch: list[dict]) -> bool:
    """将一批记录写入数据库"""
    if not batch:
        return True

    batch_tokens = sum(record["prompt_tokens"] + record["completion_tokens"] for record in batch)
    try:
        async with async_session_factory() as db:
            for record in batch:
                log_entry = TokenUsageLog(
                    provider=record["provider"],
                    model=record["model"],
                    prompt_tokens=record["prompt_tokens"],
                    completion_tokens=record["completion_tokens"],
                    session_id=record.get("session_id"),
                    course_id=record.get("course_id"),
                    purpose=record.get("purpose", "unspecified"),
                    estimated_cost_usd=record.get("estimated_cost_usd", 0.0),
                )
                db.add(log_entry)
            await db.commit()
        global _pending_tokens
        _pending_tokens = max(0, _pending_tokens - batch_tokens)
        return True
    except Exception:
        logger.exception(
            "Failed to flush token usage batch (%d records retained for retry)",
            len(batch),
        )
        return False


async def _periodic_cleanup(interval_seconds: int = 3600) -> None:
    """定期清理 90 天前记录的后台循环（每小时执行一次）"""
    while not _shutdown_event.is_set():
        try:
            await asyncio.wait_for(
                _shutdown_event.wait(), timeout=interval_seconds
            )
            # shutdown_event 被设置，退出
            break
        except asyncio.TimeoutError:
            # 超时 = 到了清理时间
            await cleanup_old_records()


async def start_worker() -> None:
    """启动后台 worker 和定期清理任务（在应用 lifespan 启动阶段调用）"""
    global _worker_task, _cleanup_task

    _shutdown_event.clear()

    _worker_task = asyncio.create_task(_worker())
    _cleanup_task = asyncio.create_task(_periodic_cleanup())

    logger.info("TokenCounter worker & cleanup task started")


async def stop_worker() -> None:
    """优雅关闭后台 worker 和清理任务（在应用 lifespan 关闭阶段调用）"""
    _shutdown_event.set()

    tasks = []
    if _worker_task:
        tasks.append(_worker_task)
    if _cleanup_task:
        tasks.append(_cleanup_task)

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    logger.info("TokenCounter worker & cleanup task stopped")
