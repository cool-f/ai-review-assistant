"""
Admin API — Token 用量监控接口

端点:
  GET  /api/admin/token-usage              — 按天聚合用量
  GET  /api/admin/token-usage/by-provider  — 按提供商分组用量
  GET  /api/admin/token-usage/budget       — 预算检查

认证:
  所有端点通过 X-Admin-Key 请求头校验。
  未配置 ADMIN_API_KEY 时打印 warning 并允许访问（开发模式）。
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from backend.config import get_settings
from backend.schemas.admin import (
    DailyUsageItem,
    DailyUsageResponse,
    ProviderUsageItem,
    ProviderUsageResponse,
    BudgetResponse,
)
from backend.services.token_counter import (
    get_daily_usage,
    get_usage_by_provider,
    check_budget,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── 认证依赖 ──────────────────────────────────────────
async def verify_admin_key(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> None:
    """
    校验 X-Admin-Key 请求头。

    - 如果未配置 ADMIN_API_KEY（空字符串），打印 warning 并放行（开发模式）。
    - 如果已配置，要求请求头必须匹配，否则返回 403。
    """
    settings = get_settings()
    configured_key = settings.ADMIN_API_KEY

    if not configured_key:
        logger.warning(
            "ADMIN_API_KEY is NOT configured — admin endpoints are open. "
            "Set ADMIN_API_KEY in .env / environment to secure admin routes."
        )
        return  # 开发模式：放行

    if not x_admin_key:
        raise HTTPException(
            status_code=403,
            detail="Missing X-Admin-Key header — admin access requires authentication.",
        )

    if x_admin_key != configured_key:
        raise HTTPException(
            status_code=403,
            detail="Invalid X-Admin-Key — admin access denied.",
        )


# ── 路由 ────────────────────────────────────────────

@router.get(
    "/token-usage",
    response_model=DailyUsageResponse,
    summary="按天聚合 Token 用量",
)
async def token_usage_daily(
    days: int = Query(default=7, ge=1, le=90, description="统计最近 N 天"),
    _auth: None = Depends(verify_admin_key),
):
    """获取最近 N 天每日聚合的 Token 用量数据"""
    items = await get_daily_usage(days=days)
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
    _auth: None = Depends(verify_admin_key),
):
    """获取最近 N 天按 AI 提供商分组的 Token 用量"""
    items = await get_usage_by_provider(days=days)
    return ProviderUsageResponse(
        days=days,
        items=[ProviderUsageItem(**item) for item in items],
    )


@router.get(
    "/token-usage/budget",
    response_model=BudgetResponse,
    summary="检查今日 Token 预算",
)
async def token_usage_budget(
    _auth: None = Depends(verify_admin_key),
):
    """
    检查今日 Token 用量是否超出预算上限

    - `within_budget`: True 表示今日用量未超预算
    - `warning`: 当用量 >= 80% 预算时为告警文字，超出预算时为超限警告
    """
    result = await check_budget()
    return BudgetResponse(**result)
