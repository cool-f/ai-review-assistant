"""Courseware ingestion orchestration.

This application service owns the end-to-end state transition from an uploaded
document to extracted knowledge, embeddings, and cross-courseware links. HTTP
routes only validate ownership and schedule this use case.
"""

import asyncio
import logging

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from review_assistant.infrastructure.ai.embeddings import EmbeddingService
from review_assistant.infrastructure.persistence.database import async_session_factory
from review_assistant.infrastructure.persistence.models import (
    Chunk,
    Courseware,
    Example,
    KnowledgePoint,
    KnowledgePointLink,
)
from review_assistant.infrastructure.usage.context import usage_scope

logger = logging.getLogger(__name__)


def plan_ingestion_retry(
    *, force: bool, status: str, failed_stage: str | None, has_knowledge: bool
) -> str:
    """Choose a retry that never destroys learning data implicitly."""
    if force:
        return "full"
    if failed_stage in {"embedding", "linking"} and has_knowledge:
        return failed_stage
    if status == "completed" or has_knowledge:
        return "force_required"
    return "restart"

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
    from review_assistant.infrastructure.documents.text_extractor import TextExtractor
    from review_assistant.application.courseware.extractor import AIExtractor

    # 创建独立的数据库会话（后台任务不能使用请求级会话）
    async with async_session_factory() as db:
        current_stage = "parse"
        try:
            # ── 1. 查找课件记录 ─────────────────
            result = await db.execute(
                select(Courseware).where(Courseware.id == courseware_id)
            )
            courseware = result.scalar_one_or_none()
            if not courseware:
                logger.error("提取流水线: 课件 %s 不存在", courseware_id)
                return

            courseware.status = "processing"
            courseware.failed_stage = None
            courseware.parse_status = "processing"
            await db.commit()

            # ── 2. 提取全文或 Vision 识别 ───────
            text = ""
            page_count = None
            knowledge_points_data: list[dict] = []

            if use_vision and file_type == "pdf":
                # Vision 路径：逐页视觉识别提取知识点
                logger.info("Vision 提取: courseware_id=%s", courseware_id)
                from review_assistant.infrastructure.documents.text_extractor import TextExtractor

                with usage_scope("vision_extraction", course_id=courseware.course_id):
                    knowledge_points_data, page_count = await TextExtractor._extract_pdf_via_vision(file_path)
                if page_count is not None:
                    courseware.page_count = page_count

                vision_text = "\n\n".join(
                    f"[[PAGE:{kp.get('page_ref') if isinstance(kp.get('page_ref'), int) else 0}]]\n"
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

                courseware.parse_status = "completed"
                courseware.knowledge_status = "processing"
                await db.commit()

                # ── 3. AI 提取知识点 ────────────────
                current_stage = "knowledge"
                logger.info("开始 AI 提取: courseware_id=%s", courseware_id)
                with usage_scope("courseware_extraction", course_id=courseware.course_id):
                    extraction_result = await AIExtractor.extract_knowledge_points(text)
                knowledge_points_data = extraction_result.get("knowledge_points", [])
                logger.info(
                    "AI 提取完成: courseware_id=%s, 知识点数=%d",
                    courseware_id,
                    len(knowledge_points_data),
                )

            if use_vision and file_type == "pdf":
                courseware.parse_status = "completed"
                courseware.knowledge_status = "processing"
                await db.commit()

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
                    page_number=cd.get("page_number"),
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

            courseware.knowledge_status = "completed"
            courseware.embedding_status = "processing"
            await db.commit()

            # ── 6. 生成嵌入向量 ─────────────────
            current_stage = "embedding"
            partial_failure = False
            try:
                with usage_scope("embedding", course_id=courseware.course_id):
                    await _generate_and_save_embeddings(
                        db, created_kps, created_examples, created_chunks,
                        embed_service=embed_service,
                    )
                courseware.embedding_status = "completed"
            except Exception as embed_exc:
                # 嵌入失败不阻塞流水线，知识点和例题已入库
                logger.warning(
                    "嵌入向量生成失败（知识点提取已完成）: %s", embed_exc
                )
                partial_failure = True
                courseware.embedding_status = "failed"
                courseware.failed_stage = "embedding"
                courseware.error_message = f"知识点提取成功，但嵌入生成失败: {embed_exc}"[:2048]

            courseware.linking_status = "processing"
            await db.commit()

            # ── 7. 发现知识点关联 ───────────────
            current_stage = "linking"
            if created_kps:
                try:
                    from review_assistant.application.knowledge.linking import LinkingService

                    linker = LinkingService(db)
                    new_kp_ids = [kp.id for kp in created_kps]
                    link_count = await linker.find_links(new_kp_ids)
                    logger.info("关联发现完成: 写入 %d 条关联", link_count)
                    courseware.linking_status = "completed"
                except Exception as link_exc:
                    # 关联发现失败不阻塞提取流水线
                    logger.warning("关联发现失败（不影响知识点提取）: %s", link_exc)
                    partial_failure = True
                    courseware.linking_status = "failed"
                    courseware.failed_stage = "linking"
                    courseware.error_message = f"知识点已提取，但关联发现失败: {link_exc}"[:2048]
            else:
                courseware.linking_status = "completed"

            # ── 8. 标记完成 ─────────────────────
            courseware.status = "partial" if partial_failure else "completed"
            if not partial_failure:
                courseware.error_message = None
                courseware.failed_stage = None
            await db.commit()
            logger.info("提取流水线完成: courseware_id=%s", courseware_id)

        except Exception as exc:
            logger.exception("提取流水线失败: courseware_id=%s", courseware_id)
            # Never commit partially flushed chunks/knowledge on an early-stage
            # failure. Roll back first, then persist only the lifecycle state.
            try:
                await db.rollback()
                courseware = await db.get(Courseware, courseware_id)
                if courseware is None:
                    return
                courseware.status = "failed"
                setattr(courseware, f"{current_stage}_status", "failed")
                courseware.failed_stage = current_stage
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

async def resume_extraction_pipeline(
    courseware_id: str,
    stage: str,
    embed_service: EmbeddingService | None = None,
) -> None:
    """Resume embedding/linking from durable extracted data without deleting it."""
    if stage not in {"embedding", "linking"}:
        raise ValueError(f"unsupported resume stage: {stage}")

    async with async_session_factory() as db:
        courseware = await db.get(Courseware, courseware_id)
        if courseware is None:
            return
        kps = list((await db.execute(
            select(KnowledgePoint).where(KnowledgePoint.courseware_id == courseware_id)
        )).scalars().all())
        if not kps:
            courseware.status = "failed"
            courseware.failed_stage = "knowledge"
            courseware.error_message = "No extracted knowledge remains; an explicit full extraction is required."
            await db.commit()
            return
        examples = list((await db.execute(
            select(Example).where(Example.courseware_id == courseware_id)
        )).scalars().all())
        chunks = list((await db.execute(
            select(Chunk).where(Chunk.courseware_id == courseware_id)
        )).scalars().all())

        if stage == "embedding":
            courseware.status = "processing"
            courseware.embedding_status = "processing"
            courseware.linking_status = "pending"
            courseware.failed_stage = None
            courseware.error_message = None
            await db.commit()
            try:
                with usage_scope("embedding", course_id=courseware.course_id):
                    await _generate_and_save_embeddings(
                        db, kps, examples, chunks, embed_service=embed_service
                    )
                courseware.embedding_status = "completed"
                courseware.linking_status = "processing"
                await db.commit()
            except Exception as exc:
                await db.rollback()
                courseware = await db.get(Courseware, courseware_id)
                if courseware is not None:
                    courseware.status = "partial"
                    courseware.embedding_status = "failed"
                    courseware.failed_stage = "embedding"
                    courseware.error_message = f"Embedding retry failed: {exc}"[:2048]
                    await db.commit()
                return

        if stage == "linking":
            courseware = await db.get(Courseware, courseware_id)
            if courseware is None:
                return
            courseware.status = "processing"
            courseware.linking_status = "processing"
            courseware.failed_stage = None
            courseware.error_message = None
            await db.commit()
        kp_ids = [kp.id for kp in kps]
        try:
            await db.execute(delete(KnowledgePointLink).where(or_(
                KnowledgePointLink.source_kp_id.in_(kp_ids),
                KnowledgePointLink.target_kp_id.in_(kp_ids),
            )))
            from review_assistant.application.knowledge.linking import LinkingService

            await LinkingService(db).find_links(kp_ids)
            courseware.linking_status = "completed"
            courseware.status = "completed"
            courseware.failed_stage = None
            courseware.error_message = None
            await db.commit()
        except Exception as exc:
            await db.rollback()
            courseware = await db.get(Courseware, courseware_id)
            if courseware is not None:
                courseware.status = "partial"
                courseware.linking_status = "failed"
                courseware.failed_stage = "linking"
                courseware.error_message = f"Linking retry failed: {exc}"[:2048]
                await db.commit()


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
