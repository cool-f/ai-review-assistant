"""
聊天服务：三层上下文构建 + SSE 流式响应 + 消息持久化

三层上下文 token 预算:
  - System 层:  ~500  tokens (角色设定 + 行为规则)
  - 持久层:    ~2000 tokens (语义搜索相关知识点/文本块)
  - 滑动窗口:  ~4000 tokens (最近 10 轮对话)

持久层使用 pgvector 向量相似度搜索:
  用户问题 → query embedding → chunks/knowledge_points <=> 搜索 → top-K 上下文
"""

import json
import logging
import math
import asyncio
import hashlib
from datetime import datetime, timezone
from typing import AsyncIterator

from sqlalchemy import select, text as sa_text, bindparam
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from pgvector.sqlalchemy import Vector

from review_assistant.infrastructure.persistence.models import (
    Course,
    ChatSession,
    ChatMessage,
    ChatRequest,
    Courseware,
    KnowledgePoint,
    Chunk,
)
from review_assistant.infrastructure.ai.client import get_ai_client, AbstractAIClient
from review_assistant.infrastructure.usage.context import usage_scope
from review_assistant.domain.idempotency import resolve_chat_request


# ── Token 计数器 ────────────────────────────────────
try:
    import tiktoken

    _ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENCODING = None


def count_tokens(text: str) -> int:
    """估算文本 token 数；tiktoken 不可用时退化为字符数/3.5 估算"""
    if _ENCODING is not None:
        try:
            return len(_ENCODING.encode(text))
        except Exception:
            pass
    return max(1, math.ceil(len(text) / 3.5))


# ── 语义搜索参数 ───────────────────────────────────
_TOP_K_CHUNKS = 5          # chunks 搜索返回数
_TOP_K_KPS = 3             # knowledge_points 搜索返回数
_MIN_SIMILARITY = 0.5      # 最低相似度阈值（过低的结果不纳入上下文）


logger = logging.getLogger(__name__)


def assemble_model_messages(system_prompt: str, history: list[dict], current: str) -> list[dict]:
    """Build model input while guaranteeing that the current prompt appears once."""
    messages = [{"role": "system", "content": system_prompt}, *history]
    if not history or history[-1].get("role") != "user" or history[-1].get("content") != current:
        messages.append({"role": "user", "content": current})
    return messages


# ═══════════════════════════════════════════════════════
# 系统提示词模板
# ═══════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是"期末复习助手"，一位耐心、专业的学习导师。你的职责是：

1. **解答疑问**：用清晰、结构化的方式回答学生关于课程知识的问题。
2. **引导思考**：不要直接给答案，先引导学生自己思考，再逐步给出解析。
3. **引用课件**：如果提供了课件知识点上下文，请优先引用其中的内容来回答问题。
4. **举一反三**：讲解完一个知识点后，可以主动提供相关例题帮助巩固。
5. **友好语气**：用鼓励、亲切的语气与学生交流，适当使用表情符号活跃气氛。

注意事项：
- 回答应准确、基于课件内容，不要臆造知识点。
- 如果问题超出课件范围，诚实说明并建议学生查阅其他资料。
- 遇到不确定的问题时，可以反问学生澄清需求。
- 使用 Markdown 格式组织长回答（标题、列表、代码块等），但避免过度使用。"""


# ═══════════════════════════════════════════════════════
# ChatService
# ═══════════════════════════════════════════════════════

class ChatService:
    """
    聊天业务逻辑

    职责:
      - 根据 session 构建三层上下文
      - 使用 pgvector 语义搜索构建知识上下文（替代旧的全量拼接）
      - 调用 AI 客户端流式生成回复
      - 持久化对话记录
    """

    MAX_ROUNDS = 10          # 滑动窗口最大轮数
    SYSTEM_BUDGET = 500      # 系统提示词 token 预算
    PERSISTENT_BUDGET = 2000 # 持久上下文 token 预算
    WINDOW_BUDGET = 4000     # 滑动窗口 token 预算

    def __init__(self, db: AsyncSession):
        self.db = db
        self._ai_client: AbstractAIClient | None = None
        self._embed_service = None  # 延迟初始化

    @property
    def ai_client(self) -> AbstractAIClient:
        """延迟初始化 AI 客户端"""
        if self._ai_client is None:
            self._ai_client = get_ai_client()
        return self._ai_client

    # ── 上下文构建 ──────────────────────────────────

    async def build_context(
        self, session_id: str, user_query: str = ""
    ) -> tuple[str, list[dict], list[dict]]:
        """
        构建三层上下文，返回 (system_prompt, messages_list)

        三层结构:
          1. System 层: 角色设定 (~500 tokens)
          2. 持久层:   语义搜索相关知识点 (~2000 tokens)
          3. 滑动窗口: 最近 10 轮对话 (~4000 tokens)

        Args:
            session_id: 会话 ID
            user_query: 用户当前问题（用于语义搜索，为空时回退到列表拼接）

        Returns:
            (system_prompt, [{"role":..., "content":...}, ...])
        """
        session = await self._get_session(session_id)

        # ── Layer 1: System ────────────────────────
        system_prompt = SYSTEM_PROMPT

        # ── Layer 2: Persistent (语义搜索课件知识) ─
        if user_query.strip():
            knowledge_context, citations = await self._build_semantic_context(
                session.course_id, session.courseware_id, user_query
            )
        else:
            knowledge_context, citations = await self._build_knowledge_context_fallback(
                session.course_id, session.courseware_id
            )

        if knowledge_context:
            system_prompt += "\n\n---\n\n## 课件相关知识\n\n" + knowledge_context

        # ── Layer 3: Sliding Window ────────────────
        history_messages = await self._get_recent_messages(
            session_id, limit=self.MAX_ROUNDS * 2
        )
        window_messages = self._fit_sliding_window(
            history_messages,
            max_tokens=self.WINDOW_BUDGET,
        )

        return system_prompt, window_messages, citations

    async def _get_session(self, session_id: str) -> ChatSession:
        """获取会话，不存在时抛出异常"""
        result = await self.db.execute(
            select(ChatSession)
            .options(selectinload(ChatSession.courseware))
            .where(ChatSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise ValueError(f"会话不存在: {session_id}")
        return session

    async def _build_semantic_context(
        self, course_id: str, courseware_id: str | None, query: str
    ) -> tuple[str, list[dict]]:
        """
        使用 pgvector 语义搜索构建知识上下文

        策略:
          1. 生成 query embedding
          2. 在 chunks 表中搜索 top-K 最相似的文本块（限定课件范围）
          3. 在 knowledge_points 表中搜索 top-K 最相似的知识点
          4. 合并去重，控制 token 预算

        Args:
            courseware_id: 当前选中的课件 ID（None 表示搜索全部课件）
            query: 用户问题文本

        Returns:
            格式化后的知识上下文字符串
        """
        try:
            from review_assistant.infrastructure.ai.embeddings import EmbeddingService

            embed_service = EmbeddingService()
            try:
                query_embedding = await embed_service.embed_single(
                    query, text_type="query"
                )
            finally:
                await embed_service.close()

            # ── 1. 搜索 chunks ──────────────────────
            chunk_results = await self._vector_search_chunks(
                query_embedding, course_id, courseware_id, _TOP_K_CHUNKS
            )

            # ── 2. 搜索 knowledge_points ────────────
            kp_results = await self._vector_search_kps(
                query_embedding, course_id, courseware_id, _TOP_K_KPS
            )

            # ── 3. 合并构建上下文 ────────────────────
            return (
                self._format_search_results(chunk_results, kp_results, self.PERSISTENT_BUDGET),
                self._build_citations(chunk_results, kp_results),
            )

        except Exception:
            logger.exception("语义搜索失败，回退到全量知识点列表")
            return await self._build_knowledge_context_fallback(
                course_id, courseware_id
            )

    async def _vector_search_chunks(
        self,
        embedding: list[float],
        course_id: str,
        courseware_id: str | None,
        limit: int,
    ) -> list[dict]:
        """
        pgvector 余弦相似度搜索 chunks

        Returns:
            [{"content": str, "similarity": float, "courseware_id": str}, ...]
        """
        conditions = ["c.embedding IS NOT NULL", "cw.course_id = :course_id"]
        params: dict = {
            "embedding": embedding,
            "course_id": course_id,
            "limit_val": limit,
            "min_sim": _MIN_SIMILARITY,
        }

        if courseware_id:
            conditions.append("c.courseware_id = :cw_id")
            params["cw_id"] = courseware_id

        where_clause = " AND ".join(conditions)

        raw_sql = sa_text(f"""
            SELECT
                c.content,
                1 - (c.embedding <=> :embedding) AS similarity,
                c.courseware_id,
                c.page_number,
                cw.title AS courseware_title
            FROM chunks c
            JOIN coursewares cw ON cw.id = c.courseware_id
            WHERE {where_clause}
              AND 1 - (c.embedding <=> :embedding) > :min_sim
            ORDER BY c.embedding <=> :embedding
            LIMIT :limit_val
        """).bindparams(bindparam("embedding", type_=Vector(1024)))

        result = await self.db.execute(raw_sql, params)
        return [
            {
                "content": row.content,
                "similarity": round(float(row.similarity), 4),
                "courseware_id": row.courseware_id,
                "courseware_title": row.courseware_title,
                "page_number": row.page_number,
            }
            for row in result
        ]

    async def _vector_search_kps(
        self,
        embedding: list[float],
        course_id: str,
        courseware_id: str | None,
        limit: int,
    ) -> list[dict]:
        """
        pgvector 余弦相似度搜索 knowledge_points

        Returns:
            [{"title": str, "content": str, "similarity": float,
              "courseware_id": str}, ...]
        """
        conditions = ["kp.embedding IS NOT NULL", "cw.course_id = :course_id"]
        params: dict = {
            "embedding": embedding,
            "course_id": course_id,
            "limit_val": limit,
            "min_sim": _MIN_SIMILARITY,
        }

        if courseware_id:
            conditions.append("kp.courseware_id = :cw_id")
            params["cw_id"] = courseware_id

        where_clause = " AND ".join(conditions)

        raw_sql = sa_text(f"""
            SELECT
                kp.title,
                kp.content,
                1 - (kp.embedding <=> :embedding) AS similarity,
                kp.courseware_id,
                kp.id AS knowledge_point_id,
                kp.page_number,
                cw.title AS courseware_title
            FROM knowledge_points kp
            JOIN coursewares cw ON cw.id = kp.courseware_id
            WHERE {where_clause}
              AND 1 - (kp.embedding <=> :embedding) > :min_sim
            ORDER BY kp.embedding <=> :embedding
            LIMIT :limit_val
        """).bindparams(bindparam("embedding", type_=Vector(1024)))

        result = await self.db.execute(raw_sql, params)
        return [
            {
                "title": row.title,
                "content": row.content,
                "similarity": round(float(row.similarity), 4),
                "courseware_id": row.courseware_id,
                "courseware_title": row.courseware_title,
                "knowledge_point_id": row.knowledge_point_id,
                "page_number": row.page_number,
            }
            for row in result
        ]

    def _format_search_results(
        self,
        chunks: list[dict],
        kps: list[dict],
        token_budget: int,
    ) -> str:
        """将语义搜索结果格式化为上下文字符串，控制在 token 预算内"""
        if not chunks and not kps:
            return ""

        lines: list[str] = []
        used = 0
        header = "以下是与你的问题最相关的课件内容，请优先引用：\n"
        header_tokens = count_tokens(header)
        remaining = token_budget - header_tokens

        # 先展示知识点（结构化，信息密度高）
        if kps:
            lines.append("### 相关知识点")
            for kp in kps:
                line = (
                    f"- **{kp['title']}** (相关度: {kp['similarity']})\n"
                    f"  {kp['content'][:400]}"
                )
                line_tokens = count_tokens(line)
                if used + line_tokens > remaining:
                    break
                lines.append(line)
                used += line_tokens

        # 再展示文本块（更细粒度的原文上下文）
        if chunks:
            if lines:
                lines.append("")
            lines.append("### 相关课件原文")
            for ch in chunks:
                snippet = ch["content"][:500]
                line = (
                    f"> {snippet}\n"
                    f"  (相关度: {ch['similarity']})"
                )
                line_tokens = count_tokens(line)
                if used + line_tokens > remaining:
                    break
                lines.append(line)
                used += line_tokens

        return header + "\n".join(lines) if lines else ""

    @staticmethod
    def _build_citations(chunks: list[dict], kps: list[dict]) -> list[dict]:
        citations: list[dict] = []
        seen: set[tuple] = set()
        for item in [*kps, *chunks]:
            key = (item.get("courseware_id"), item.get("page_number"), item.get("knowledge_point_id"))
            if key in seen:
                continue
            seen.add(key)
            citations.append({
                "courseware_id": item.get("courseware_id"),
                "courseware_title": item.get("courseware_title", "课件"),
                "knowledge_point_id": item.get("knowledge_point_id"),
                "page_number": item.get("page_number"),
                "excerpt": (item.get("content") or item.get("title") or "")[:180],
                "similarity": item.get("similarity"),
            })
        return citations[:8]

    async def _build_knowledge_context_fallback(
        self, course_id: str, courseware_id: str | None
    ) -> tuple[str, list[dict]]:
        """
        回退方案：当语义搜索不可用时，按 order_index 拼接知识点

        策略:
          1. 查询课件下所有知识点
          2. 按 order_index 排序
          3. 逐个拼接，超出 token 预算时截断
        """
        conditions = [Courseware.course_id == course_id]
        if courseware_id:
            conditions.append(KnowledgePoint.courseware_id == courseware_id)
        result = await self.db.execute(
            select(KnowledgePoint, Courseware.title.label("courseware_title"))
            .join(Courseware, Courseware.id == KnowledgePoint.courseware_id)
            .where(*conditions)
            .order_by(Courseware.title, KnowledgePoint.order_index)
        )
        rows = list(result.all())
        kps = [row[0] for row in rows]

        if not kps:
            return "", []

        lines: list[str] = []
        used = 0
        remaining = self.PERSISTENT_BUDGET - count_tokens(
            "以下是从课件中提取的知识点，请优先引用：\n"
        )

        for kp in kps:
            line = f"- **{kp.title}**: {kp.content[:300]}"
            line_tokens = count_tokens(line)
            if used + line_tokens > remaining:
                lines.append(f"\n（还有 {len(kps) - len(lines)} 个知识点未列出）")
                break
            lines.append(line)
            used += line_tokens

        context = (
            "以下是从课件中提取的知识点，请优先引用：\n" + "\n".join(lines)
            if lines else ""
        )
        citations = [
            {
                "courseware_id": kp.courseware_id,
                "courseware_title": courseware_title,
                "knowledge_point_id": kp.id,
                "page_number": kp.page_number,
                "excerpt": kp.content[:180],
                "similarity": None,
            }
            for kp, courseware_title in rows[:8]
        ]
        return context, citations

    async def _get_recent_messages(
        self, session_id: str, limit: int
    ) -> list[dict]:
        """获取最近 N 条历史消息（按时间升序）"""
        result = await self.db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.role.in_(["user", "assistant"]),
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        messages = list(reversed(list(result.scalars().all())))

        return [
            {"role": m.role, "content": m.content}
            for m in messages
        ]

    def _fit_sliding_window(
        self, messages: list[dict], max_tokens: int
    ) -> list[dict]:
        """将消息列表压缩到 max_tokens 以内"""
        if not messages:
            return []

        token_counts = [count_tokens(m["content"]) for m in messages]
        total = sum(token_counts)
        if total <= max_tokens:
            return messages

        keep_from = 0
        for i in range(len(messages) - 1):
            total -= token_counts[i]
            if total <= max_tokens:
                keep_from = i + 1
                break
        else:
            keep_from = len(messages) - 1

        return messages[keep_from:]

    # ── 流式聊天 ────────────────────────────────────

    async def stream_chat(
        self, session_id: str, user_message: str, idempotency_key: str
    ) -> AsyncIterator[str]:
        """
        流式聊天 — 异步生成器，yield SSE 格式的字符串

        SSE 格式:
          data: {"type":"chunk","content":"..."}\n\n
          data: {"type":"done","message_id":"...","token_count":N}\n\n
          data: {"type":"error","message":"..."}\n\n

        Args:
            session_id:   会话 ID
            user_message: 用户输入消息

        Yields:
            SSE 格式的字符串行
        """
        user_token_count = count_tokens(user_message)
        content_hash = hashlib.sha256(user_message.encode("utf-8")).hexdigest()
        chat_request: ChatRequest | None = None

        try:
            request_result = await self.db.execute(
                select(ChatRequest).where(ChatRequest.idempotency_key == idempotency_key)
            )
            chat_request = request_result.scalar_one_or_none()
            action = resolve_chat_request(
                chat_request.status if chat_request else None,
                content_matches=(
                    chat_request is None
                    or (chat_request.session_id == session_id and chat_request.content_hash == content_hash)
                ),
            )
            if action == "conflict":
                yield _sse_event({"type": "error", "message": "幂等键已用于另一条消息，请重新发送"})
                return
            if action == "wait":
                yield _sse_event({"type": "error", "message": "该消息仍在处理中，请稍后刷新会话"})
                return
            if action == "replay":
                assistant = await self.db.get(ChatMessage, chat_request.assistant_message_id)
                if assistant is None:
                    chat_request.status = "failed"
                    await self.db.commit()
                else:
                    yield _sse_event({"type": "replace", "content": assistant.content})
                    yield _sse_event({
                        "type": "done", "message_id": assistant.id,
                        "token_count": assistant.token_count, "citations": assistant.citations or [],
                        "replayed": True,
                    })
                    return

            if action == "start":
                user_msg = ChatMessage(
                    session_id=session_id, role="user", content=user_message,
                    token_count=user_token_count,
                )
                self.db.add(user_msg)
                await self.db.flush()
                chat_request = ChatRequest(
                    session_id=session_id,
                    idempotency_key=idempotency_key,
                    content_hash=content_hash,
                    user_message_id=user_msg.id,
                    status="processing",
                )
                self.db.add(chat_request)
            else:
                chat_request.status = "processing"
                chat_request.error_message = None
            await self.db.commit()

            # 2. 构建上下文（传入用户问题用于语义搜索）
            session_for_usage = await self._get_session(session_id)
            with usage_scope("chat_retrieval", course_id=session_for_usage.course_id, session_id=session_id):
                system_prompt, history, citations = await self.build_context(
                    session_id, user_query=user_message
                )

            # 3. 组装消息列表
            messages = assemble_model_messages(system_prompt, history, user_message)

            # 4. 流式调用 AI
            full_response = ""
            with usage_scope("chat", course_id=session_for_usage.course_id, session_id=session_id):
                async for chunk in self.ai_client.chat_stream(
                    messages,
                    temperature=0.7,
                ):
                    full_response += chunk
                    yield _sse_event({"type": "chunk", "content": chunk})

            # 5. 保存助手消息
            assistant_token_count = count_tokens(full_response)
            assistant_msg = ChatMessage(
                session_id=session_id,
                role="assistant",
                content=full_response,
                token_count=assistant_token_count,
                citations=citations,
            )
            self.db.add(assistant_msg)
            await self.db.flush()
            chat_request.assistant_message_id = assistant_msg.id
            chat_request.status = "completed"
            chat_request.error_message = None
            await self.db.commit()
            await self.db.refresh(assistant_msg)

            # 6. 更新会话时间
            session = await self._get_session(session_id)
            session.updated_at = datetime.now(timezone.utc)
            self.db.add(session)
            await self.db.commit()

            # 7. 发送完成事件
            yield _sse_event({
                "type": "done",
                "message_id": assistant_msg.id,
                "token_count": assistant_token_count,
                "citations": citations,
            })

        except asyncio.CancelledError:
            await self.db.rollback()
            if chat_request is not None:
                retry_request = await self.db.get(ChatRequest, chat_request.id)
                if retry_request:
                    retry_request.status = "failed"
                    retry_request.error_message = "连接中断，可安全重试"
                    await self.db.commit()
            raise
        except Exception as exc:
            logger.exception("stream_chat 发生未预期异常 session_id=%s", session_id)
            await self.db.rollback()
            if chat_request is not None:
                retry_request = await self.db.get(ChatRequest, chat_request.id)
                if retry_request:
                    retry_request.status = "failed"
                    retry_request.error_message = str(exc)[:2048]
                    await self.db.commit()
            yield _sse_event({
                "type": "error",
                "message": str(exc) if "预算" in str(exc) else "服务器内部错误，请稍后重试",
            })

    # ── 消息持久化 ──────────────────────────────────

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        token_count: int | None = None,
    ) -> ChatMessage:
        """保存一条消息到数据库"""
        if token_count is None:
            token_count = count_tokens(content)

        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            token_count=token_count,
        )
        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)
        return message

    # ── 会话管理 ────────────────────────────────────

    async def create_session(
        self,
        title: str = "",
        course_id: str = "",
        courseware_id: str | None = None,
    ) -> ChatSession:
        """创建新的聊天会话"""
        if not course_id or await self.db.get(Course, course_id) is None:
            raise ValueError(f"课程不存在: {course_id}")
        if courseware_id:
            result = await self.db.execute(
                select(Courseware).where(
                    Courseware.id == courseware_id,
                    Courseware.course_id == course_id,
                )
            )
            if result.scalar_one_or_none() is None:
                raise ValueError(f"课件不存在: {courseware_id}")

        if not title:
            title = "新对话"

        session = ChatSession(
            title=title,
            course_id=course_id,
            courseware_id=courseware_id,
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def get_history(
        self, session_id: str
    ) -> list[ChatMessage]:
        """获取会话的完整历史消息（按时间升序）"""
        result = await self.db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        )
        return list(result.scalars().all())


# ── SSE 工具 ─────────────────────────────────────────

def _sse_event(data: dict) -> str:
    """将字典序列化为 SSE data 行"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
