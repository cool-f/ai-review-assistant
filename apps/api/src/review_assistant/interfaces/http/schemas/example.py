"""
例题相关 Pydantic v2 Schema

包含:
  - ExampleResponse:     例题响应
  - ExampleListResponse: 例题列表响应
"""

from datetime import datetime
from pydantic import BaseModel, ConfigDict


# ── 例题响应 ──────────────────────────────────────
class ExampleResponse(BaseModel):
    """例题响应（独立版本，与 knowledge_point.py 中定义兼容）"""
    id: str
    courseware_id: str
    knowledge_point_id: str | None = None
    question: str
    answer: str
    explanation: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── 例题列表响应 ──────────────────────────────────
class ExampleListResponse(BaseModel):
    """例题列表"""
    examples: list[ExampleResponse]
    knowledge_point_id: str
    total: int
