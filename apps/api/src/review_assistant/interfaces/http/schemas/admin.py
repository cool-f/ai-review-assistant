"""
Admin API 的 Pydantic 请求/响应模型 (v2)
"""

from typing import Optional

from pydantic import BaseModel, Field


class DailyUsageItem(BaseModel):
    """单天用量"""
    date: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    call_count: int


class DailyUsageResponse(BaseModel):
    """按天用量响应"""
    days: int
    items: list[DailyUsageItem]


class ProviderUsageItem(BaseModel):
    """单提供商用量"""
    provider: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    call_count: int


class ProviderUsageResponse(BaseModel):
    """按提供商用量响应"""
    days: int
    items: list[ProviderUsageItem]


class PurposeUsageItem(BaseModel):
    purpose: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    call_count: int


class PurposeUsageResponse(BaseModel):
    days: int
    items: list[PurposeUsageItem]


class BudgetResponse(BaseModel):
    """预算状态"""
    today_usage: int
    daily_budget: int
    percentage: float
    within_budget: bool
    call_count_today: int
    warning: Optional[str] = Field(None, description="超 80% 或超出预算时的告警信息")
