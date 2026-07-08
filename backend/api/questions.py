"""
题目生成 API 路由

端点:
  POST   /api/knowledge-points/{kp_id}/generate-questions  — AI 生成题目 (SSE 流式)
  GET    /api/questions                                   — 分页列表
  GET    /api/questions/{question_id}                     — 详情
  DELETE /api/questions/{question_id}                     — 删除
"""

import math

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services.question_service import QuestionGenerationService

router = APIRouter(prefix="/api", tags=["questions"])


# ═══════════════════════════════════════════════════════
# 内联 Pydantic Schema
# ═══════════════════════════════════════════════════════

class GenerateQuestionsRequest(BaseModel):
    """生成题目请求"""
    count: int = Field(default=3, ge=1, le=10, description="生成题目数量")
    question_type: str = Field(
        default="auto",
        description="题型偏好: auto | 选择题 | 填空题 | 计算题 | 证明题",
    )


class QuestionResponse(BaseModel):
    """题目响应"""
    id: str
    courseware_id: str
    knowledge_point_id: str
    question_type: str
    question_text: str
    options: list | None = None
    answer_text: str
    explanation: str | None = None
    source_style: str
    difficulty: str
    knowledge_points: list[dict] = Field(default_factory=list)
    courseware_title: str = ""
    created_at: str


class QuestionListResponse(BaseModel):
    """题目分页列表"""
    items: list[dict]
    total: int
    page: int
    size: int
    pages: int


# ═══════════════════════════════════════════════════════
# 路由处理器
# ═══════════════════════════════════════════════════════

@router.post(
    "/knowledge-points/{kp_id}/generate-questions",
    summary="AI 生成练习题",
    description="根据知识点内容调用 AI 生成练习题，返回 SSE 流式响应。",
)
async def generate_questions(
    kp_id: str,
    body: GenerateQuestionsRequest = GenerateQuestionsRequest(),
    db: AsyncSession = Depends(get_db),
):
    """
    为指定知识点生成 AI 练习题（SSE 流式响应）

    SSE 事件格式:
      data: {"type":"chunk","content":"..."}            — AI 生成文本流
      data: {"type":"question_parsed","question":{...}}  — 单道题解析完成
      data: {"type":"done","questions":[...],"total":N}  — 全部完成
      data: {"type":"error","message":"..."}            — 错误
    """
    service = QuestionGenerationService(db)

    async def event_generator():
        async for sse_line in service.generate_questions(
            kp_id=kp_id,
            count=body.count,
            question_type=body.question_type,
        ):
            yield sse_line

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/questions",
    summary="题目列表",
    description="分页查询已生成的练习题，支持按课件和知识点筛选。",
)
async def list_questions(
    courseware_id: str | None = Query(default=None, description="按课件筛选"),
    knowledge_point_id: str | None = Query(default=None, description="按知识点筛选"),
    page: int = Query(default=1, ge=1, description="页码"),
    size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    db: AsyncSession = Depends(get_db),
):
    """获取题目分页列表"""
    result = await QuestionGenerationService.list_questions(
        db=db,
        courseware_id=courseware_id,
        knowledge_point_id=knowledge_point_id,
        page=page,
        size=size,
    )
    return result


@router.get(
    "/questions/{question_id}",
    summary="题目详情",
    description="获取单道题目的详细信息，包含关联知识点。",
)
async def get_question(
    question_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取题目详情"""
    question = await QuestionGenerationService.get_question(db, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")
    return question


@router.delete(
    "/questions/{question_id}",
    status_code=204,
    summary="删除题目",
    description="删除指定的生成题目。",
)
async def delete_question(
    question_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除题目"""
    deleted = await QuestionGenerationService.delete_question(db, question_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="题目不存在")
    return None
