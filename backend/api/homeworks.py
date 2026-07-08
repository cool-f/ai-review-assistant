"""
作业管理 API 路由

端点:
  POST   /api/homeworks/upload     — 上传作业文件 (自动提取题目)
  GET    /api/homeworks/           — 分页列表
  GET    /api/homeworks/{id}       — 作业详情 (含解答与知识点关联)
  DELETE /api/homeworks/{id}       — 删除作业及关联数据
  GET    /api/homeworks/{id}/solve — 触发 AI 解答 (SSE 流式)
"""

import asyncio
import hashlib
import math
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import get_settings
from backend.database import get_db
from backend.models import Homework, Solution, SolutionKnowledgePoint
from backend.schemas.homework import (
    HomeworkResponse,
    HomeworkDetailResponse,
    HomeworkListResponse,
    SolutionResponse,
    SolutionKnowledgePointRef,
)
from backend.services.text_extractor import TextExtractor
from backend.services.homework_service import HomeworkService


router = APIRouter(prefix="/api/homeworks", tags=["homeworks"])

settings = get_settings()

# 允许的文件扩展名 -> 类型映射 (同课件)
ALLOWED_EXTENSIONS = {
    ".pdf": "pdf",
    ".pptx": "pptx",
    ".docx": "docx",
    ".txt": "txt",
    ".md": "md",
}


# ═══════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════

def _sanitize_filename(filename: str) -> str:
    """安全化文件名：仅保留字母数字、中文、点、横线、下划线"""
    safe = "".join(
        c if c.isalnum() or c in "._-" or "一" <= c <= "鿿" else "_"
        for c in filename
    )
    if not safe or safe == "_":
        safe = "untitled"
    return safe


def _get_storage_dir(homework_id: str) -> Path:
    """返回作业文件的存储目录"""
    upload_dir = Path(settings.UPLOAD_DIR).resolve()
    return upload_dir / "homeworks" / homework_id


# ═══════════════════════════════════════════════════════
# POST /upload
# ═══════════════════════════════════════════════════════

@router.post("/upload", response_model=HomeworkDetailResponse, status_code=201)
async def upload_homework(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    上传作业文件

    - 支持格式: pdf / pptx / docx / txt / md
    - 文件大小限制: 50 MB
    - 上传后自动提取纯文本并切分题目，创建 Solution 记录
    - 题目切分后状态为 'completed'，可通过 /solve 触发 AI 解答
    """
    # ── 1. 校验文件扩展名 ─────────────────────
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext}。支持: {', '.join(ALLOWED_EXTENSIONS.keys())}",
        )

    file_type = ALLOWED_EXTENSIONS[ext]

    # ── 2. 读取并校验文件大小 ─────────────────
    content = await file.read()

    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件大小超出限制 ({settings.MAX_UPLOAD_SIZE // 1024 // 1024}MB)",
        )

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="上传的文件为空")

    # ── 3. 保存文件到磁盘 ─────────────────────
    hw_id = str(uuid.uuid4())
    storage_dir = _get_storage_dir(hw_id)
    storage_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _sanitize_filename(file.filename)
    file_path = storage_dir / safe_name
    file_path.write_bytes(content)

    # ── 4. 计算文件哈希 ───────────────────────
    file_hash = hashlib.sha256(content).hexdigest()

    # ── 5. 标题 ───────────────────────────────
    title = Path(file.filename).stem or file.filename

    # ── 6. 提取全文 (线程池执行) ──────────────
    try:
        full_text, _page_count = await asyncio.to_thread(
            TextExtractor.extract, str(file_path), file_type
        )
    except Exception as e:
        # 清理已保存的文件
        shutil.rmtree(str(storage_dir), ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail=f"文件文本提取失败: {str(e)}",
        )

    # ── 7. 切分题目 ──────────────────────────
    questions = HomeworkService.extract_questions(full_text)

    if not questions:
        # 清理已保存的文件
        shutil.rmtree(str(storage_dir), ignore_errors=True)
        raise HTTPException(
            status_code=400,
            detail="未能从文件中识别到任何题目，请检查文件内容",
        )

    # ── 8. 写入数据库 ─────────────────────────
    homework = Homework(
        id=hw_id,
        title=title,
        file_path=str(file_path),
        file_type=file_type,
        file_size=len(content),
        file_hash=file_hash,
        status="completed",  # 题目已提取，等待 AI 解答
    )
    db.add(homework)

    for q in questions:
        solution = Solution(
            homework_id=hw_id,
            question_number=q["question_number"],
            question_text=q["question_text"],
            answer_text=None,   # 待 AI 解答
        )
        db.add(solution)

    await db.commit()
    await db.refresh(homework)

    # ── 9. 构建响应 (含刚创建的 solutions) ───
    return await _build_detail_response(homework, db)


# ═══════════════════════════════════════════════════════
# GET / — 分页列表
# ═══════════════════════════════════════════════════════

@router.get("/", response_model=HomeworkListResponse)
async def list_homeworks(
    page: int = 1,
    size: int = 20,
    folder_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """获取作业分页列表，按创建时间倒序。可选 folder_id 筛选（传 "null" 表示查根目录）"""
    if page < 1:
        page = 1
    if size < 1:
        size = 1
    if size > 100:
        size = 100

    # 构建查询条件
    conditions = []
    if folder_id is not None:
        if folder_id == "null":
            conditions.append(Homework.folder_id.is_(None))
        else:
            conditions.append(Homework.folder_id == folder_id)

    # 查询总数
    count_query = select(func.count(Homework.id))
    if conditions:
        count_query = count_query.where(*conditions)
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    pages = max(1, math.ceil(total / size)) if total > 0 else 0

    # 分页查询
    offset = (page - 1) * size
    query = select(Homework).order_by(Homework.created_at.desc())
    if conditions:
        query = query.where(*conditions)
    result = await db.execute(query.offset(offset).limit(size))
    items = list(result.scalars().all())

    return HomeworkListResponse(
        items=items,
        total=total,
        page=page,
        size=size,
        pages=pages,
    )


# ═══════════════════════════════════════════════════════
# GET /{id} — 作业详情 (含解答及知识点关联)
# ═══════════════════════════════════════════════════════

@router.get("/{homework_id}", response_model=HomeworkDetailResponse)
async def get_homework(
    homework_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取作业详情，包含全部解答及关联的知识点"""
    result = await db.execute(
        select(Homework)
        .options(selectinload(Homework.solutions))
        .where(Homework.id == homework_id)
    )
    homework = result.scalar_one_or_none()

    if not homework:
        raise HTTPException(status_code=404, detail="作业不存在")

    return await _build_detail_response(homework, db)


# ═══════════════════════════════════════════════════════
# DELETE /{id} — 删除作业
# ═══════════════════════════════════════════════════════

@router.delete("/{homework_id}", status_code=204)
async def delete_homework(
    homework_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    删除作业 (级联删除关联的 solutions、solution_knowledge_points)

    同时清理磁盘上的上传文件。
    """
    result = await db.execute(
        select(Homework).where(Homework.id == homework_id)
    )
    homework = result.scalar_one_or_none()

    if not homework:
        raise HTTPException(status_code=404, detail="作业不存在")

    # 记录磁盘路径
    storage_dir = (
        Path(homework.file_path).parent
        if homework.file_path else None
    )

    # 删除数据库记录 (CASCADE 自动清理关联表)
    await db.delete(homework)
    await db.commit()

    # 清理磁盘文件
    if storage_dir and storage_dir.exists():
        upload_root = Path(settings.UPLOAD_DIR).resolve()
        resolved_dir = storage_dir.resolve()
        if not resolved_dir.is_relative_to(upload_root):
            raise HTTPException(
                status_code=500,
                detail="存储目录路径异常，拒绝删除",
            )
        try:
            shutil.rmtree(str(resolved_dir))
        except OSError:
            pass

    return None


# ═══════════════════════════════════════════════════════
# GET /{id}/solve — AI 解答 (SSE 流式)
# ═══════════════════════════════════════════════════════

@router.get("/{homework_id}/solve")
async def solve_homework(
    homework_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    触发 AI 批量解答 (Server-Sent Events 流式)

    仅解答 answer_text 为空的题目，已解答的自动跳过。
    最多同时 3 个 AI 请求并行解答。

    SSE 事件格式:
      data: {"type":"token","question_number":1,"content":"..."}

      data: {"type":"question_done","question_number":1,"solution_id":"..."}

      data: {"type":"question_error","question_number":2,"message":"..."}

      data: {"type":"match_result","solution_id":"...","matches":[...]}

      data: {"type":"done","homework_id":"...","solved_count":N}
    """
    # 确认作业存在
    hw_result = await db.execute(
        select(Homework).where(Homework.id == homework_id)
    )
    homework = hw_result.scalar_one_or_none()

    if not homework:
        raise HTTPException(status_code=404, detail="作业不存在")

    if homework.status == "processing":
        raise HTTPException(
            status_code=409,
            detail="作业正在解答中，请等待当前任务完成后再试",
        )

    service = HomeworkService(db)

    async def event_generator():
        async for sse_line in service.batch_solve(homework_id):
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


# ═══════════════════════════════════════════════════════
# 内部辅助
# ═══════════════════════════════════════════════════════

async def _build_detail_response(
    homework: Homework,
    db: AsyncSession,
) -> HomeworkDetailResponse:
    """
    构建作业详情响应，含解答列表及各自的知识点关联

    始终使用显式 selectinload 查询，一次性 eager-load 全部嵌套关系。
    回避 hasattr 探测（SQLAlchemy ORM 对象永远通过 hasattr 检查，
    但若未显式加载关系属性，访问时可能触发 MissingGreenlet 或 N+1 查询）。
    """
    sol_result = await db.execute(
        select(Solution)
        .options(
            selectinload(Solution.knowledge_point_links).selectinload(
                SolutionKnowledgePoint.knowledge_point
            )
        )
        .where(Solution.homework_id == homework.id)
        .order_by(Solution.question_number)
    )
    solutions = list(sol_result.scalars().all())

    solution_responses: list[SolutionResponse] = []
    for sol in solutions:
        # 获取知识点关联
        kp_refs: list[SolutionKnowledgePointRef] = []
        if sol.knowledge_point_links:
            for link in sol.knowledge_point_links:
                kp_title = ""
                if link.knowledge_point:
                    kp_title = link.knowledge_point.title
                kp_refs.append(SolutionKnowledgePointRef(
                    id=link.id,
                    knowledge_point_id=link.knowledge_point_id,
                    knowledge_point_title=kp_title,
                    relevance_score=link.relevance_score,
                    match_method=link.match_method,
                ))

        solution_responses.append(SolutionResponse(
            id=sol.id,
            question_number=sol.question_number,
            question_text=sol.question_text,
            answer_text=sol.answer_text,
            thinking_process=sol.thinking_process,
            created_at=sol.created_at,
            knowledge_point_links=kp_refs,
        ))

    return HomeworkDetailResponse(
        id=homework.id,
        title=homework.title,
        file_type=homework.file_type,
        file_size=homework.file_size,
        status=homework.status,
        error_message=homework.error_message,
        created_at=homework.created_at,
        updated_at=homework.updated_at,
        solutions=solution_responses,
    )
