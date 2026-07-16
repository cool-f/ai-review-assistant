"""
Admin API — Token 用量监控接口

端点:
  GET  /api/admin/token-usage              — 按天聚合用量
  GET  /api/admin/token-usage/by-provider  — 按提供商分组用量
  GET  /api/admin/token-usage/budget       — 预算检查

单用户本地模式下不增加独立登录或管理密钥。
"""

from fastapi import APIRouter, Query

from review_assistant.interfaces.http.schemas.admin import (
    DailyUsageItem,
    DailyUsageResponse,
    ProviderUsageItem,
    ProviderUsageResponse,
    BudgetResponse,
    PurposeUsageItem,
    PurposeUsageResponse,
)
from review_assistant.infrastructure.usage.token_counter import (
    get_daily_usage,
    get_usage_by_provider,
    check_budget,
    get_usage_by_purpose,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── 路由 ────────────────────────────────────────────

@router.get(
    "/token-usage",
    response_model=DailyUsageResponse,
    summary="按天聚合 Token 用量",
)
async def token_usage_daily(
    days: int = Query(default=7, ge=1, le=90, description="统计最近 N 天"),
    course_id: str | None = None,
):
    """获取最近 N 天每日聚合的 Token 用量数据"""
    items = await get_daily_usage(days=days, course_id=course_id)
    return DailyUsageResponse(
        days=days,
        items=[DailyUsageItem(**item) for item in items],
    )


@router.get(
    "/token-usage/by-provider",
    response_model=ProviderUsageResponse,
    summary="按提供商分组 Token 用量",
)
async def token_usage_by_provider(
    days: int = Query(default=7, ge=1, le=90, description="统计最近 N 天"),
    course_id: str | None = None,
):
    """获取最近 N 天按 AI 提供商分组的 Token 用量"""
    items = await get_usage_by_provider(days=days, course_id=course_id)
    return ProviderUsageResponse(
        days=days,
        items=[ProviderUsageItem(**item) for item in items],
    )


@router.get("/token-usage/by-purpose", response_model=PurposeUsageResponse)
async def token_usage_by_purpose(
    days: int = Query(default=7, ge=1, le=90),
    course_id: str | None = None,
):
    items = await get_usage_by_purpose(days=days, course_id=course_id)
    return PurposeUsageResponse(days=days, items=[PurposeUsageItem(**item) for item in items])


@router.get(
    "/token-usage/budget",
    response_model=BudgetResponse,
    summary="检查今日 Token 预算",
)
async def token_usage_budget(
):
    """
    检查今日 Token 用量是否超出预算上限

    - `within_budget`: True 表示今日用量未超预算
    - `warning`: 当用量 >= 80% 预算时为告警文字，超出预算时为超限警告
    """
    result = await check_budget()
    return BudgetResponse(**result)
