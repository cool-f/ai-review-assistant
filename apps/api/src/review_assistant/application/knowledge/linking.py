"""
LinkingService — 基于 pgvector 余弦相似度的知识点关联发现服务

职责:
  - 给定新入库知识点 ID 列表，计算其 embedding 与已有知识点 embedding 的余弦相似度
  - 相似度 > 阈值 (默认 0.85) 的记录写入 knowledge_point_links 表
  - 自动去重（source_kp_id < target_kp_id）
  - 使用 pgvector <=> 运算符（余弦距离），相似度 = 1 - 余弦距离

约束:
  - 批量关联 100 个新 KP 耗时 < 5 秒
  - CHECK(source_kp_id <> target_kp_id) 和 UNIQUE(source, target) 约束
"""

import logging
import uuid

from sqlalchemy import bindparam, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from pgvector.sqlalchemy import Vector

from review_assistant.core.config import get_settings
from review_assistant.infrastructure.persistence.models import KnowledgePoint, KnowledgePointLink

logger = logging.getLogger(__name__)

# 每个新 KP 最多匹配的候选数（ORDER BY ... LIMIT）
_CANDIDATE_LIMIT = 10


class LinkingService:
    """
    知识点关联发现服务

    使用 pgvector <=> 运算符计算余弦距离，将高相似度 (> threshold)
    的知识点对写入 knowledge_point_links 表。

    Usage:
        service = LinkingService(db)
        link_count = await service.find_links(["kp_uuid_1", "kp_uuid_2"])
    """

    def __init__(
        self,
        db: AsyncSession,
        threshold: float | None = None,
    ):
        """
        Args:
            db: 数据库会话
            threshold: 相似度阈值（0.0 ~ 1.0）。未指定时从配置读取 LINKING_SIMILARITY_THRESHOLD。
        """
        self.db = db
        if threshold is None:
            settings = get_settings()
            threshold = settings.LINKING_SIMILARITY_THRESHOLD
        self.threshold = threshold

    # ── 公开接口 ──────────────────────────────────────

    async def find_links(self, new_kp_ids: list[str]) -> int:
        """
        为新入库知识点查找并创建关联

        对每个新 KP 执行 pgvector 余弦相似度查询 (<=> 运算符)，
        筛选 similarity > threshold 的候选并写入 knowledge_point_links。

        Args:
            new_kp_ids: 新入库知识点 ID 列表

        Returns:
            int: 实际写入的关联记录数（去重后）

        Raises:
            RuntimeError: 数据库查询或写入失败
        """
        if not new_kp_ids:
            return 0

        # ── 1. 批量获取新 KP 的 embedding ──────────────
        kp_embeddings = await self._fetch_embeddings(new_kp_ids)
        if not kp_embeddings:
            logger.warning("find_links: 没有可用的 embedding，跳过关联发现")
            return 0

        logger.info(
            "开始关联发现: %d 个新 KP (阈值=%.2f, limit=%d)",
            len(kp_embeddings),
            self.threshold,
            _CANDIDATE_LIMIT,
        )

        # ── 2. 对每个新 KP 执行相似度查询 ──────────────
        all_candidates: list[tuple[str, str, float]] = []

        for kp_id, embedding in kp_embeddings.items():
            candidates = await self._query_similar(
                kp_id=kp_id,
                embedding=embedding,
                limit=_CANDIDATE_LIMIT,
            )
            all_candidates.extend(candidates)

        if not all_candidates:
            logger.info("find_links: 未找到满足阈值的关联")
            return 0

        logger.info("find_links: 原始候选关联数=%d", len(all_candidates))

        # ── 3. 去重（source < target，保留最高相似度）──
        unique_links = self._deduplicate(all_candidates)
        logger.info("find_links: 去重后关联数=%d", len(unique_links))

        # ── 4. 批量写入 ───────────────────────────────
        inserted = await self._bulk_insert_links(unique_links)
        logger.info("find_links: 成功写入 %d 条关联记录", inserted)

        return inserted

    # ── 内部 ──────────────────────────────────────────

    async def _fetch_embeddings(
        self, kp_ids: list[str]
    ) -> dict[str, list[float]]:
        """
        批量获取知识点的 embedding

        Returns:
            dict: {kp_id: embedding_list}，跳过 embedding 为 NULL 的记录
        """
        result = await self.db.execute(
            select(KnowledgePoint.id, KnowledgePoint.embedding).where(
                KnowledgePoint.id.in_(kp_ids)
            )
        )
        embeddings: dict[str, list[float]] = {}
        for row in result:
            if row.embedding is not None:
                embeddings[row.id] = row.embedding
        return embeddings

    async def _query_similar(
        self,
        kp_id: str,
        embedding: list[float],
        limit: int = 10,
    ) -> list[tuple[str, str, float]]:
        """
        使用 pgvector <=> 运算符查询与给定 embedding 最相似的已有知识点

        相似度 = 1 - 余弦距离，只返回 similarity > threshold 的记录。

        Args:
            kp_id: 源知识点 ID
            embedding: 源知识点的嵌入向量
            limit: 最多返回的候选数

        Returns:
            list of (source_kp_id, target_kp_id, similarity)，source < target 已排序
        """
        # pgvector <=> 运算符：余弦距离
        # 1 - 余弦距离 = 余弦相似度
        # 对 :embedding 绑定参数显式指定 Vector(1024) 类型，
        # 确保 asyncpg/pgvector 正确编码 list[float] 为向量。
        raw_sql = text("""
            SELECT
                kp.id,
                1 - (kp.embedding <=> :embedding) AS similarity
            FROM knowledge_points kp
            JOIN coursewares cw ON cw.id = kp.courseware_id
            WHERE kp.id != :kp_id
              AND kp.embedding IS NOT NULL
              AND cw.course_id = (
                  SELECT source_cw.course_id
                  FROM knowledge_points source_kp
                  JOIN coursewares source_cw ON source_cw.id = source_kp.courseware_id
                  WHERE source_kp.id = :kp_id
              )
            ORDER BY kp.embedding <=> :embedding
            LIMIT :limit_val
        """).bindparams(bindparam("embedding", type_=Vector(1024)))

        try:
            result = await self.db.execute(
                raw_sql,
                {
                    "embedding": embedding,
                    "kp_id": kp_id,
                    "limit_val": limit,
                },
            )
        except Exception as exc:
            logger.error(
                "pgvector 相似度查询失败: kp_id=%s, error=%s", kp_id, exc
            )
            raise RuntimeError(f"pgvector 相似度查询失败: {exc}") from exc

        links: list[tuple[str, str, float]] = []
        for row in result:
            similarity = float(row.similarity)
            if similarity > self.threshold:
                other_id = row.id
                # 规范化：source < target（字符串字典序）
                source, target = sorted([kp_id, other_id])
                links.append((source, target, similarity))

        return links

    @staticmethod
    def _deduplicate(
        candidates: list[tuple[str, str, float]],
    ) -> list[tuple[str, str, float]]:
        """
        去重：同一 (source, target) 对保留相似度最高的

        Args:
            candidates: [(source, target, similarity), ...]

        Returns:
            去重后的列表
        """
        best: dict[tuple[str, str], float] = {}
        for source, target, sim in candidates:
            key = (source, target)
            if key not in best or sim > best[key]:
                best[key] = sim
        return [(s, t, sim) for (s, t), sim in best.items()]

    async def _bulk_insert_links(
        self,
        links: list[tuple[str, str, float]],
    ) -> int:
        """
        批量写入关联记录

        使用 ORM add_all + flush，依赖数据库 UNIQUE 约束防止重复插入。
        若遇到 IntegrityError (并发重复)，回滚当前事务后重新抛出，
        由上层决定是否重试。

        Args:
            links: [(source_kp_id, target_kp_id, similarity), ...]

        Returns:
            int: 写入的记录数

        Raises:
            IntegrityError: 当唯一约束冲突发生时（回滚后重新抛出）
        """
        for source, target, sim in links:
            link = KnowledgePointLink(
                id=str(uuid.uuid4()),
                source_kp_id=source,
                target_kp_id=target,
                similarity=sim,
                link_type="related",
            )
            self.db.add(link)

        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise
        return len(links)
