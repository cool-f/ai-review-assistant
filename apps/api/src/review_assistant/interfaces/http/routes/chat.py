"""
聊天 API 路由

端点:
  POST   /api/chat/sessions              — 创建新会话
  GET    /api/chat/sessions              — 分页列表
  GET    /api/chat/sessions/{id}/messages — 获取历史消息
  POST   /api/chat/sessions/{id}/messages — 发送消息 (SSE 流式)
"""

import math

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from review_assistant.infrastructure.persistence.database import get_db
from review_assistant.infrastructure.persistence.models import ChatSession, ChatMessage
from review_assistant.interfaces.http.schemas.chat import (
    ChatSessionCreate,
    ChatSessionResponse,
    ChatSessionListResponse,
    ChatMessageCreate,
    ChatMessageResponse,
    ChatHistoryResponse,
)
from review_assistant.application.chat.service import ChatService
from review_assistant.application.chat.jobs import get_or_start_chat_job

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ═══════════════════════════════════════════════════════
# 会话 CRUD
# ═══════════════════════════════════════════════════════

@router.post(
    "/sessions",
    response_model=ChatSessionResponse,
    status_code=201,
)
async def create_session(
    body: ChatSessionCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建新的聊天会话"""
    service = ChatService(db)
    try:
        session = await service.create_session(
            title=body.title,
            course_id=body.course_id,
            courseware_id=body.courseware_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ChatSessionResponse(
        id=session.id,
        course_id=session.course_id,
        title=session.title,
        courseware_id=session.courseware_id,
        message_count=0,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.get(
    "/sessions",
    response_model=ChatSessionListResponse,
)
async def list_sessions(
    course_id: str,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取会话分页列表，按更新时间倒序"""
    # 查询总数
    count_result = await db.execute(select(func.count(ChatSession.id)).where(ChatSession.course_id == course_id))
    total = count_result.scalar() or 0

    pages = max(1, math.ceil(total / size)) if total > 0 else 0

    offset = (page - 1) * size
    # 子查询统计消息数，避免 selectinload 拉取全部消息正文
    msg_count_subq = (
        select(func.count(ChatMessage.id))
        .where(ChatMessage.session_id == ChatSession.id)
        .correlate(ChatSession)
        .scalar_subquery()
    )
    result = await db.execute(
        select(ChatSession, msg_count_subq.label("message_count"))
        .where(ChatSession.course_id == course_id)
        .order_by(desc(ChatSession.updated_at))
        .offset(offset)
        .limit(size)
    )
    rows = result.all()

    items = [
        ChatSessionResponse(
            id=s.id,
            course_id=s.course_id,
            title=s.title,
            courseware_id=s.courseware_id,
            message_count=count or 0,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s, count in rows
    ]

    return ChatSessionListResponse(
        items=items,
        total=total,
        page=page,
        size=size,
        pages=pages,
    )


@router.get(
    "/sessions/{session_id}",
    response_model=ChatSessionResponse,
)
async def get_session(
    session_id: str,
    course_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取单个会话详情"""
    msg_count_subq = (
        select(func.count(ChatMessage.id))
        .where(ChatMessage.session_id == ChatSession.id)
        .correlate(ChatSession)
        .scalar_subquery()
    )
    result = await db.execute(
        select(ChatSession, msg_count_subq.label("message_count"))
        .where(ChatSession.id == session_id, ChatSession.course_id == course_id)
    )
    row = result.one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="会话不存在")

    session, message_count = row
    return ChatSessionResponse(
        id=session.id,
        course_id=session.course_id,
        title=session.title,
        courseware_id=session.courseware_id,
        message_count=message_count or 0,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=204,
)
async def delete_session(
    session_id: str,
    course_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除会话及其所有消息（级联删除）"""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.course_id == course_id,
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    await db.delete(session)
    await db.commit()
    return None


# ═══════════════════════════════════════════════════════
# 消息
# ═══════════════════════════════════════════════════════

@router.get(
    "/sessions/{session_id}/messages",
    response_model=ChatHistoryResponse,
)
async def get_history(
    session_id: str,
    course_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取会话的历史消息（按时间升序）"""
    # 先确认会话存在
    session_check = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.course_id == course_id,
        )
    )
    if session_check.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    service = ChatService(db)
    messages = await service.get_history(session_id)

    return ChatHistoryResponse(
        session_id=session_id,
        messages=[
            ChatMessageResponse(
                id=m.id,
                session_id=m.session_id,
                role=m.role,
                content=m.content,
                token_count=m.token_count,
                citations=m.citations or [],
                created_at=m.created_at,
            )
            for m in messages
        ],
        total=len(messages),
    )


@router.post(
    "/sessions/{session_id}/messages",
)
async def send_message(
    session_id: str,
    body: ChatMessageCreate,
    course_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    发送消息并获取 AI 流式回复 (Server-Sent Events)

    请求体: {"content": "用户消息内容"}

    响应格式 (text/event-stream):
      data: {"type":"chunk","content":"增量文本"}

      data: {"type":"done","message_id":"...","token_count":N}

      data: {"type":"error","message":"错误描述"}
    """
    # 确认会话存在
    session_check = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.course_id == course_id,
        )
    )
    if session_check.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    async def event_generator():
        job = await get_or_start_chat_job(
            session_id=session_id,
            content=body.content,
            idempotency_key=body.idempotency_key,
        )
        async for sse_line in job.subscribe():
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
