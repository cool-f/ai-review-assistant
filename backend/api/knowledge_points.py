"""
知识点 API 路由

端点:
  GET  /api/coursewares/{courseware_id}/knowledge-points          — 获取课件的知识点列表
  POST /api/coursewares/{courseware_id}/knowledge-points/extract  — 触发知识点提取
  GET  /api/knowledge-points/{kp_id}                               — 获取单个知识点详情

同时导出 run_extraction_pipeline() 供 coursewares 路由的 upload 处理器调用。
"""

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db, async_session_factory
from backend.models import Courseware, KnowledgePoint, Example, Chunk
from backend.services.embedding_service import EmbeddingService
from backend.schemas.knowledge_point import (
    KnowledgePointResponse,
    KnowledgePointListResponse,
    ExtractRequest,
    ExtractStatusResponse,
)

logger = logging.getLogger(__name__)

# ── 路由器 1: 按课件操作知识点 ──────────────────
# 路径中的 {courseware_id} 由 FastAPI 自动注入到路由函数
courseware_kp_router = APIRouter(
    prefix="/api/coursewares/{courseware_id}/knowledge-points",
    tags=["knowledge-points"],
)

# ── 路由器 2: 知识点单条查询 ────────────────────
kp_router = APIRouter(
    prefix="/api/knowledge-points",
    tags=["knowledge-points"],
)


# ═══════════════════════════════════════════════════
# 路由处理器
# ═══════════════════════════════════════════════════

@courseware_kp_router.get("/", response_model=KnowledgePointListResponse)
async def list_knowledge_points(
    courseware_id: str,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """
    获取指定课件的知识点分页列表

    每个知识点会附带其关联的例题列表。
    """
    # 验证课件存在
    cw_result = await db.execute(
        select(Courseware).where(Courseware.id == courseware_id)
    )
    if not cw_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="课件不存在")

    if page < 1:
        page = 1
    if size < 1:
        size = 1
    if size > 100:
        size = 100

    # 查询总数
    count_result = await db.execute(
        select(func.count(KnowledgePoint.id)).where(
            KnowledgePoint.courseware_id == courseware_id
        )
    )
    total = count_result.scalar() or 0

    pages = max(1, (total + size - 1) // size) if total > 0 else 0

    # 分页查询知识点（预加载例题）
    offset = (page - 1) * size
    result = await db.execute(
        select(KnowledgePoint)
        .options(selectinload(KnowledgePoint.examples))
        .where(KnowledgePoint.courseware_id == courseware_id)
        .order_by(KnowledgePoint.order_index, KnowledgePoint.created_at)
        .offset(offset)
        .limit(size)
    )
    items = list(result.scalars().all())

    return KnowledgePointListResponse(
        items=items,
        total=total,
        page=page,
        size=size,
        pages=pages,
    )


@courseware_kp_router.post("/extract", response_model=ExtractStatusResponse)
async def extract_knowledge_points(
    courseware_id: str,
    background_tasks: BackgroundTasks,
    body: ExtractRequest = ExtractRequest(),
    db: AsyncSession = Depends(get_db),
):
    """
    触发知识点 AI 提取（异步后台执行）

    - 课件必须存在且状态不能为 processing
    - 提取在后台执行，完成后自动更新课件状态
    - 重新提取前会清理已有的知识点、例题和文本块
    """
    # 验证课件存在
    result = await db.execute(
        select(Courseware).where(Courseware.id == courseware_id)
    )
    courseware = result.scalar_one_or_none()
    if not courseware:
        raise HTTPException(status_code=404, detail="课件不存在")

    if courseware.status == "processing":
        raise HTTPException(
            status_code=409,
            detail="课件正在处理中，请等待当前任务完成后再试",
        )

    # 标记为处理中
    courseware.status = "processing"
    courseware.error_message = None
    await db.commit()

    # 启动后台提取任务
    # re_extract=True：重新提取（清理已有数据 + 重建 chunks）
    # use_vision 从课件记录中读取，保持与首次上传一致的管线
    background_tasks.add_task(
        run_extraction_pipeline,
        courseware_id,
        str(courseware.file_path),
        courseware.file_type,
        re_extract=True,
        use_vision=courseware.use_vision,
    )

    return ExtractStatusResponse(
        courseware_id=courseware_id,
        status="processing",
        message="知识点提取已启动，请稍后查询结果",
    )


@kp_router.get("/{kp_id}", response_model=KnowledgePointResponse)
async def get_knowledge_point(
    kp_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取单个知识点详情（含关联例题）
    """
    result = await db.execute(
        select(KnowledgePoint)
        .options(selectinload(KnowledgePoint.examples))
        .where(KnowledgePoint.id == kp_id)
    )
    kp = result.scalar_one_or_none()
    if not kp:
        raise HTTPException(status_code=404, detail="知识点不存在")

    return kp


# ═══════════════════════════════════════════════════
# 提取流水线（后台任务）
# ═══════════════════════════════════════════════════

async def run_extraction_pipeline(
    courseware_id: str,
    file_path: str,
    file_type: str,
    re_extract: bool = False,
    use_vision: bool = False,
    embed_service: EmbeddingService | None = None,
) -> None:
    """
    知识点提取完整流水线（作为 FastAPI BackgroundTask 运行）

    流程:
      1. 提取课件全文
      2. 调用 AI 提取知识点和例题
      3. 清理旧数据（如为重新提取）
      4. 写入知识点和例题到数据库
      5. 生成嵌入向量并更新入库
      6. 更新课件状态

    Args:
        courseware_id: 课件 ID
        file_path: 课件文件路径
        file_type: 文件类型 (pdf/pptx/docx/txt/md)
        re_extract: 是否为重新提取（True 时会清理已有数据并重建 chunks）
        embed_service: 可选的嵌入服务实例（用于测试 mock 注入）。
                       传入时使用传入实例，否则函数内部自行创建。
    """
    from backend.services.text_extractor import TextExtractor
    from backend.services.ai_extractor import AIExtractor

    # 创建独立的数据库会话（后台任务不能使用请求级会话）
    async with async_session_factory() as db:
        try:
            # ── 1. 查找课件记录 ─────────────────
            result = await db.execute(
                select(Courseware).where(Courseware.id == courseware_id)
            )
            courseware = result.scalar_one_or_none()
            if not courseware:
                logger.error("提取流水线: 课件 %s 不存在", courseware_id)
                return

            # ── 2. 提取全文或 Vision 识别 ───────
            text = ""
            page_count = None
            knowledge_points_data: list[dict] = []

            if use_vision and file_type == "pdf":
                # Vision 路径：逐页视觉识别提取知识点
                logger.info("Vision 提取: courseware_id=%s", courseware_id)
                from backend.services.text_extractor import TextExtractor

                knowledge_points_data, page_count = await TextExtractor._extract_pdf_via_vision(file_path)
                if page_count is not None:
                    courseware.page_count = page_count

                vision_text = "\n\n".join(
                    f"{kp.get('name', '')}\n{kp.get('summary', '')}"
                    for kp in knowledge_points_data
                )
                courseware.original_text = vision_text[:1_000_000]

                logger.info(
                    "Vision 提取完成: courseware_id=%s, 知识点数=%d",
                    courseware_id,
                    len(knowledge_points_data),
                )
            else:
                # 标准文本路径
                text, page_count = await asyncio.to_thread(
                    TextExtractor.extract, file_path, file_type
                )
                if page_count is not None:
                    courseware.page_count = page_count
                courseware.original_text = text[:1_000_000]

                # ── 3. AI 提取知识点 ────────────────
                logger.info("开始 AI 提取: courseware_id=%s", courseware_id)
                extraction_result = await AIExtractor.extract_knowledge_points(text)
                knowledge_points_data = extraction_result.get("knowledge_points", [])
                logger.info(
                    "AI 提取完成: courseware_id=%s, 知识点数=%d",
                    courseware_id,
                    len(knowledge_points_data),
                )

            # ── 4. 重新提取时清理旧数据 ──────────
            if re_extract:
                await _cleanup_existing_data(db, courseware_id)

            # 首次上传也需要建 chunks；re_extract 时先清旧再建新
            # chunks 将在步骤 6 中生成 embedding
            chunk_source = text if not (use_vision and file_type == "pdf") else vision_text
            chunks_data = TextExtractor.chunk_text(chunk_source)
            created_chunks: list[Chunk] = []
            for cd in chunks_data:
                chunk = Chunk(
                    courseware_id=courseware_id,
                    content=cd["content"],
                    chunk_index=cd["chunk_index"],
                    page_number=None,
                    token_count=_count_tokens(cd["content"]),
                )
                db.add(chunk)
                created_chunks.append(chunk)

            # ── 5. 写入知识点和例题 ──────────────
            created_kps: list[KnowledgePoint] = []
            created_examples: list[Example] = []

            for i, kp_data in enumerate(knowledge_points_data):
                # 构建 content：包含难度标记 + 摘要
                difficulty = kp_data.get("difficulty", "中等")
                summary = kp_data.get("summary", "")
                content = f"【难度：{difficulty}】\n{summary}"

                kp = KnowledgePoint(
                    courseware_id=courseware_id,
                    title=kp_data.get("name", f"知识点 {i+1}"),
                    content=content,
                    page_number=kp_data.get("page_ref"),
                    order_index=i,
                )
                db.add(kp)
                created_kps.append(kp)

                # 写入例题（先用 flush 获取 kp.id）
                examples_data = kp_data.get("examples", [])
                if examples_data:
                    await db.flush()  # 确保 kp.id 已生成
                    for ex_data in examples_data:
                        example = Example(
                            courseware_id=courseware_id,
                            knowledge_point_id=kp.id,
                            question=ex_data.get("question", ""),
                            answer=ex_data.get("answer", ""),
                            explanation=ex_data.get("explanation", ""),
                        )
                        db.add(example)
                        created_examples.append(example)

            await db.flush()  # 确保所有 ID 已生成
            logger.info(
                "写入数据库: %d 个知识点, %d 个例题",
                len(created_kps),
                len(created_examples),
            )

            # ── 6. 生成嵌入向量 ─────────────────
            try:
                await _generate_and_save_embeddings(
                    db, created_kps, created_examples, created_chunks,
                    embed_service=embed_service,
                )
            except Exception as embed_exc:
                # 嵌入失败不阻塞流水线，知识点和例题已入库
                logger.warning(
                    "嵌入向量生成失败（知识点提取已完成）: %s", embed_exc
                )
                courseware.error_message = f"知识点提取成功，但嵌入生成失败: {embed_exc}"

            # ── 7. 发现知识点关联 ───────────────
            if created_kps:
                try:
                    from backend.services.linking_service import LinkingService

                    linker = LinkingService(db)
                    new_kp_ids = [kp.id for kp in created_kps]
                    link_count = await linker.find_links(new_kp_ids)
                    logger.info("关联发现完成: 写入 %d 条关联", link_count)
                except Exception as link_exc:
                    # 关联发现失败不阻塞提取流水线
                    logger.warning("关联发现失败（不影响知识点提取）: %s", link_exc)

            # ── 8. 标记完成 ─────────────────────
            courseware.status = "completed"
            courseware.error_message = None
            await db.commit()
            logger.info("提取流水线完成: courseware_id=%s", courseware_id)

        except Exception as exc:
            logger.exception("提取流水线失败: courseware_id=%s", courseware_id)
            # 尝试更新课件状态（可能事务已中止，需要新会话）
            try:
                courseware.status = "failed"
                courseware.error_message = str(exc)[:2048]
                await db.commit()
            except Exception:
                # 如果当前会话已不可用，用新会话更新
                await _update_courseware_status_failed(
                    courseware_id, str(exc)[:2048]
                )


# ═══════════════════════════════════════════════════
# 内部辅助函数
# ═══════════════════════════════════════════════════

async def _cleanup_existing_data(
    db: AsyncSession, courseware_id: str
) -> None:
    """
    清理课件下已有的例题、知识点和文本块（bulk delete，单条 SQL 完成）

    删除顺序遵循 FK 约束：
      1. examples             — knowledge_point_id → knowledge_points (SET NULL)
      2. knowledge_points     — courseware_id → coursewares (CASCADE)
      3. chunks               — courseware_id → coursewares (CASCADE)

    使用 SQLAlchemy delete().where() 语法，一次 DELETE 语句完成整批操作，
    不再逐条 SELECT + 循环 delete。
    """
    # 1. 批量删除例题
    result = await db.execute(
        delete(Example).where(Example.courseware_id == courseware_id)
    )
    logger.debug("已删除 %d 条例题", result.rowcount)

    # 2. 批量删除知识点
    result = await db.execute(
        delete(KnowledgePoint).where(
            KnowledgePoint.courseware_id == courseware_id
        )
    )
    logger.debug("已删除 %d 个知识点", result.rowcount)

    # 3. 批量删除文本块
    result = await db.execute(
        delete(Chunk).where(Chunk.courseware_id == courseware_id)
    )
    logger.debug("已删除 %d 个文本块", result.rowcount)

    await db.flush()
    logger.info("已清理课件 %s 的旧数据", courseware_id)


async def _generate_and_save_embeddings(
    db: AsyncSession,
    kps: list[KnowledgePoint],
    examples: list[Example],
    chunks: list[Chunk] | None = None,
    embed_service: EmbeddingService | None = None,
) -> None:
    """
    为知识点、例题和文本块生成嵌入向量并写回数据库

    知识点嵌入文本: title + "\n" + content
    例题嵌入文本: question + "\n" + answer
    文本块嵌入文本: content

    Args:
        db: 数据库会话
        kps: 知识点列表
        examples: 例题列表
        chunks: 文本块列表（可选）
        embed_service: 可选的嵌入服务实例（用于测试 mock 注入）。
                       传入时使用传入实例（调用方管理生命周期），
                       否则函数内部自行创建并在 finally 中关闭。
    """
    _own_service = embed_service is None
    if _own_service:
        embed_service = EmbeddingService()

    try:
        total_embedded = 0

        # ── 知识点嵌入 ─────────────────────────────
        kp_texts = [
            f"{kp.title}\n{kp.content}" for kp in kps
        ]
        if kp_texts:
            logger.info("生成 %d 条知识点嵌入向量...", len(kp_texts))
            kp_embeddings = await embed_service.embed_batch(
                kp_texts, text_type="document"
            )
            for kp, emb in zip(kps, kp_embeddings):
                kp.embedding = emb
            total_embedded += len(kp_texts)

        # ── 例题嵌入 ────────────────────────────────
        example_texts = [
            f"{ex.question}\n{ex.answer}" for ex in examples
        ]
        if example_texts:
            logger.info("生成 %d 条例题嵌入向量...", len(example_texts))
            ex_embeddings = await embed_service.embed_batch(
                example_texts, text_type="document"
            )
            for ex, emb in zip(examples, ex_embeddings):
                ex.embedding = emb
            total_embedded += len(example_texts)

        # ── 文本块嵌入 ──────────────────────────────
        if chunks:
            chunk_texts = [c.content for c in chunks if c.content.strip()]
            if chunk_texts:
                logger.info("生成 %d 条文本块嵌入向量...", len(chunk_texts))
                chunk_embeddings = await embed_service.embed_batch(
                    chunk_texts, text_type="document"
                )
                for chunk_obj, emb in zip(
                    [c for c in chunks if c.content.strip()], chunk_embeddings
                ):
                    chunk_obj.embedding = emb
                total_embedded += len(chunk_texts)

        await db.flush()
        logger.info("嵌入向量写入完成: 总计 %d 条", total_embedded)

    finally:
        if _own_service:
            await embed_service.close()


async def _update_courseware_status_failed(
    courseware_id: str, error_message: str
) -> None:
    """用新会话更新课件状态为 failed（当前会话已不可用时使用）"""
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(Courseware).where(Courseware.id == courseware_id)
            )
            cw = result.scalar_one_or_none()
            if cw:
                cw.status = "failed"
                cw.error_message = error_message
                await db.commit()
    except Exception as exc:
        logger.error("更新课件失败状态时出错: %s", exc)


def _count_tokens(text: str) -> int:
    """估算文本 token 数（使用简单字符估算）"""
    # 中文 ~1.5 字符/token, 英文 ~4 字符/token, 取折中 ~2.5 字符/token
    return max(1, len(text) // 2)
