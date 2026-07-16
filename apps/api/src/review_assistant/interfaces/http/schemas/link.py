"""
知识点关联相关 Pydantic v2 Schema

包含:
  - KnowledgePointLinkResponse:      单条关联响应
  - KnowledgePointLinksResponse:     某知识点所有双向关联响应
  - KnowledgePointLinkBrief:         关联简要信息（含知识点基本信息）
  - CoursewareCrossLinksResponse:    课件跨课件关联响应
"""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ── 关联知识点简要信息 ────────────────────────────
class LinkedKnowledgePointBrief(BaseModel):
    """关联对方知识点的简要信息"""
    id: str
    title: str
    courseware_id: str
    courseware_title: str = ""


# ── 单条关联响应 ──────────────────────────────────
class KnowledgePointLinkResponse(BaseModel):
    """单条知识点关联"""
    id: str
    source_kp_id: str
    target_kp_id: str
    similarity: float
    link_type: str = "related"
    created_at: datetime

    # 关联对方的基本信息（查询时填充）
    linked_kp: LinkedKnowledgePointBrief | None = None

    model_config = ConfigDict(from_attributes=True)


# ── 某知识点所有双向关联响应 ────────────────────────
class KnowledgePointLinksResponse(BaseModel):
    """某知识点的所有双向关联列表"""
    kp_id: str
    links: list[KnowledgePointLinkResponse] = Field(default_factory=list)
    total: int = Field(default=0, ge=0, description="关联总数")


# ── 课件跨课件关联响应 ──────────────────────────────
class CoursewareCrossLinksResponse(BaseModel):
    """课件的跨课件知识点关联列表"""
    courseware_id: str
    cross_links: list[KnowledgePointLinkResponse] = Field(default_factory=list)
    total: int = Field(default=0, ge=0, description="跨课件关联总数")
