"""
QuestionGenerationService — AI 自动出题服务

职责:
  - 根据知识点内容调用 AI 生成练习题
  - 流式 SSE 输出（复用 chat_service 的 SSE 格式）
  - 题目持久化到 generated_questions 表
  - 题目 CRUD（列表、详情、删除）
"""

import json
import logging
import math
import re
from datetime import datetime, timezone
from typing import AsyncIterator

from sqlalchemy import select, func, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import (
    KnowledgePoint,
    Example,
    Chunk,
    Courseware,
    GeneratedQuestion,
    QuestionKnowledgePoint,
)
from backend.services.ai_client import get_ai_client, AbstractAIClient

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# 出题 Prompt 模板
# ═══════════════════════════════════════════════════════

QUESTION_GEN_SYSTEM_PROMPT = """你是一位专业的教育领域出题专家。你的任务是根据知识点内容，生成适合学生复习巩固的练习题。

## 输出格式

你必须输出一个**严格合法的 JSON 数组**，每个元素是一道题目：

```json
[
  {
    "question_type": "选择题",
    "question_text": "题目正文（清晰完整）",
    "options": ["A. 选项1", "B. 选项2", "C. 选项3", "D. 选项4"],
    "answer_text": "正确答案（选择题填正确选项字母和内容，填空题填应填内容，计算题填答案和步骤，证明题填证明要点）",
    "explanation": "详细解题思路、涉及的知识点、易错点提醒",
    "difficulty": "简单"
  }
]
```

## 字段说明

- **question_type**: 必须是以下之一："选择题"、"填空题"、"计算题"、"证明题"
- **question_text**: 题目正文，清晰完整
- **options**: 选择题的 4 个选项数组（如 ["A. xxx", "B. xxx", ...]），非选择题填 null
- **answer_text**: 正确答案或解答
- **explanation**: 详细解析（必须提供，不能为空）
- **difficulty**: "简单" | "中等" | "困难"

## 题型自动推断规则

根据知识点内容特征选择最合适的题型：

| 知识点特征 | 推荐题型 | 原因 |
|-----------|---------|------|
| 概念定义、术语解释、分类特征 | 选择题 或 填空题 | 考察记忆和理解 |
| 定理、定律、性质 | 证明题 | 考察推导和逻辑 |
| 公式、计算方法、定量关系 | 计算题 | 考察应用和运算 |
| 步骤流程、操作方法 | 选择题 或 计算题 | 考察理解和应用 |
| 对比辨析、易混淆概念 | 选择题 | 考察区分能力 |

## 出题要求

1. **紧扣知识点**：每道题必须围绕提供的知识点内容设计，不能偏离
2. **梯度合理**：题目难度递进，先基础后综合
3. **选择题**：4 个选项，仅 1 个正确，错误选项要有迷惑性（常见错误、混淆概念）
4. **填空题**：空位应填写知识点中的关键词或核心公式
5. **计算题**：数据合理、步骤完整、结果可验证
6. **证明题**：明确待证结论，答案包含关键推导步骤
7. **解析详尽**：每题必须提供 explanation，包含思路分析、关键步骤、易错点
8. **模仿风格**：如果提供了参考例题，请模仿其出题风格、难度和题型分布

## 严格要求

- 只输出 JSON 数组，不要有任何前言、解释、总结或 Markdown 标记
- JSON 必须合法：双引号、正确逗号、无尾随逗号、字符串正确转义
- 输出数组长度必须恰好等于要求的数量
- 如果要求生成 3 道题，数组必须恰好有 3 个元素"""


# ═══════════════════════════════════════════════════════
# JSON 解析（复用 ai_extractor 模式）
# ═══════════════════════════════════════════════════════

def _parse_json_response(raw_text: str) -> list | dict:
    """
    解析 AI 响应中的 JSON，含多层 fallback

    策略:
      1. 直接 json.loads 整个文本
      2. 正则匹配 ```json ... ``` 代码块
      3. 正则匹配 ``` ... ``` 代码块
      4. 正则匹配最外层 [...] 数组
      5. 正则匹配最外层 {...} 对象

    Args:
        raw_text: AI 返回的原始文本

    Returns:
        解析后的 JSON 对象（list 或 dict）

    Raises:
        ValueError: 所有解析策略均失败
    """
    # 策略 1: 直接解析
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    # 策略 2: 匹配 ```json ... ```
    json_block_pattern = re.compile(r"```json\s*([\s\S]*?)\s*```", re.IGNORECASE)
    matches = json_block_pattern.findall(raw_text)
    for match in matches:
        try:
            return json.loads(match.strip())
        except json.JSONDecodeError:
            continue

    # 策略 3: 匹配 ``` ... ```（无语言标记）
    any_block_pattern = re.compile(r"```\s*([\s\S]*?)\s*```")
    matches = any_block_pattern.findall(raw_text)
    for match in matches:
        try:
            return json.loads(match.strip())
        except json.JSONDecodeError:
            continue

    # 策略 4: 匹配最外层 [...] 数组
    array_pattern = re.compile(r"\[\s*\{[\s\S]*\}\s*\]")
    array_match = array_pattern.search(raw_text)
    if array_match:
        try:
            return json.loads(array_match.group(0))
        except json.JSONDecodeError:
            pass

    # 策略 5: 匹配最外层 {...} 对象
    brace_pattern = re.compile(r"\{[\s\S]*\}")
    brace_match = brace_pattern.search(raw_text)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"无法从 AI 响应中解析 JSON。响应前 500 字符: {raw_text[:500]}"
    )


# ═══════════════════════════════════════════════════════
# SSE 工具
# ═══════════════════════════════════════════════════════

def _sse_event(data: dict) -> str:
    """将字典序列化为 SSE data 行"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ═══════════════════════════════════════════════════════
# QuestionGenerationService
# ═══════════════════════════════════════════════════════

class QuestionGenerationService:
    """AI 自动出题服务"""

    VALID_TYPES = {"选择题", "填空题", "计算题", "证明题"}
    VALID_DIFFICULTIES = {"简单", "中等", "困难"}

    def __init__(self, db: AsyncSession):
        self.db = db
        self._ai_client: AbstractAIClient | None = None

    @property
    def ai_client(self) -> AbstractAIClient:
        """延迟初始化 AI 客户端"""
        if self._ai_client is None:
            self._ai_client = get_ai_client()
        return self._ai_client

    # ── 出题 ──────────────────────────────────────────

    async def generate_questions(
        self,
        kp_id: str,
        count: int = 3,
        question_type: str = "auto",
    ) -> AsyncIterator[str]:
        """
        异步生成器：为知识点生成练习题，yield SSE 字符串

        SSE 事件类型:
          data: {"type":"chunk","content":"..."}        — AI 生成文本流
          data: {"type":"question_parsed","question":{...}}  — 单道题解析完成
          data: {"type":"done","questions":[...],"total":N}  — 全部完成
          data: {"type":"error","message":"..."}        — 错误

        Args:
            kp_id:         知识点 ID
            count:         生成题目数量（默认 3）
            question_type: 题型偏好 ("auto" 为自动推断)

        Yields:
            SSE 格式的字符串
        """
        start_time = datetime.now(timezone.utc)

        try:
            # 1. 验证并获取知识点
            result = await self.db.execute(
                select(KnowledgePoint)
                .options(selectinload(KnowledgePoint.courseware))
                .where(KnowledgePoint.id == kp_id)
            )
            kp = result.scalar_one_or_none()
            if not kp:
                yield _sse_event({
                    "type": "error",
                    "message": f"知识点不存在: {kp_id}",
                })
                return

            # 2. 获取该知识点的例题（参考格式）
            examples_result = await self.db.execute(
                select(Example)
                .where(Example.knowledge_point_id == kp_id)
                .order_by(Example.created_at)
            )
            examples = list(examples_result.scalars().all())

            # 3. 获取同课件下的相关 chunks（限制数量，避免 prompt 过长）
            chunks_result = await self.db.execute(
                select(Chunk)
                .where(Chunk.courseware_id == kp.courseware_id)
                .order_by(Chunk.chunk_index)
                .limit(10)
            )
            chunks = list(chunks_result.scalars().all())

            # 4. 构造 prompt
            system_prompt = QUESTION_GEN_SYSTEM_PROMPT

            user_prompt_parts = []

            # 知识点信息
            user_prompt_parts.append("## 知识点信息\n")
            user_prompt_parts.append(f"**知识点名称**: {kp.title}\n")
            user_prompt_parts.append(f"**知识点内容**:\n{kp.content}\n")

            # 题型偏好
            if question_type != "auto":
                user_prompt_parts.append(f"\n## 题型要求\n")
                user_prompt_parts.append(f"请全部生成为**{question_type}**类型的题目。\n")
            else:
                user_prompt_parts.append(f"\n## 题型要求\n")
                user_prompt_parts.append(f"请根据知识点内容自动推断最合适的题型（参考系统提示中的规则）。\n")

            # 参考例题
            if examples:
                user_prompt_parts.append(f"\n## 参考例题（请模仿其格式和风格）\n")
                for i, ex in enumerate(examples[:5], 1):  # 最多 5 道例题
                    user_prompt_parts.append(f"### 例题 {i}\n")
                    user_prompt_parts.append(f"**题目**: {ex.question}\n")
                    user_prompt_parts.append(f"**答案**: {ex.answer}\n")
                    if ex.explanation:
                        user_prompt_parts.append(f"**解析**: {ex.explanation}\n")
                    user_prompt_parts.append("\n")
            else:
                user_prompt_parts.append(f"\n## 参考例题\n")
                user_prompt_parts.append(f"该知识点暂无参考例题，请自行设计题目格式。\n")

            # 相关课件内容（提供上下文）
            if chunks:
                user_prompt_parts.append(f"\n## 相关课件片段（供参考，丰富题目背景）\n")
                for i, ch in enumerate(chunks[:5]):
                    snippet = ch.content[:500]
                    if len(ch.content) > 500:
                        snippet += "..."
                    user_prompt_parts.append(f"片段 {i+1}: {snippet}\n\n")

            # 生成要求
            user_prompt_parts.append(f"\n## 生成要求\n")
            user_prompt_parts.append(f"请生成 **{count}** 道练习题。\n")
            user_prompt_parts.append(f"难度建议：简单 {max(1, count * 40 // 100)} 道、中等 {max(1, count * 40 // 100)} 道、困难 {max(1, count - 2)} 道\n")

            user_prompt = "".join(user_prompt_parts)

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            # 5. 流式调用 AI
            full_response = ""
            async for chunk_text in self.ai_client.chat_stream(
                messages,
                temperature=0.7,
                max_tokens=4096,
            ):
                full_response += chunk_text
                yield _sse_event({"type": "chunk", "content": chunk_text})

            # 6. 解析 JSON 响应
            parsed = _parse_json_response(full_response)

            # 处理可能被包在 {"questions": [...]} 中的情况
            if isinstance(parsed, dict):
                if "questions" in parsed:
                    questions_data = parsed["questions"]
                else:
                    # 可能是单个题目对象被包在对象里
                    questions_data = [parsed] if any(
                        k in parsed for k in ("question_type", "question_text")
                    ) else []
            elif isinstance(parsed, list):
                questions_data = parsed
            else:
                raise ValueError(f"AI 返回了非预期的数据类型: {type(parsed).__name__}")

            if not isinstance(questions_data, list):
                raise ValueError(f"questions_data 应为列表，实际为 {type(questions_data).__name__}")

            # 限制数量
            questions_data = questions_data[:count]

            if not questions_data:
                yield _sse_event({
                    "type": "error",
                    "message": "AI 未能生成有效题目，请重试",
                })
                return

            # 7. 规范化题目数据（先验证，再批量写入）
            question_models: list[GeneratedQuestion] = []
            question_responses: list[dict] = []

            for i, q_data in enumerate(questions_data):
                if not isinstance(q_data, dict):
                    logger.warning("跳过非字典类型的题目: %s", type(q_data).__name__)
                    continue

                # 规范化和验证
                question_type_val = str(q_data.get("question_type", "选择题")).strip()
                if question_type_val not in self.VALID_TYPES:
                    question_type_val = "选择题"

                question_text = str(q_data.get("question_text", "")).strip()
                if not question_text:
                    logger.warning("跳过无题目文本的条目")
                    continue

                options = q_data.get("options")
                if question_type_val == "选择题":
                    if not isinstance(options, list) or len(options) < 2:
                        # 选择题 options 无效 → 降级为填空题
                        logger.warning(
                            "选择题 options 无效，降级为填空题: %s", question_text[:50]
                        )
                        question_type_val = "填空题"
                        options = None
                else:
                    options = None

                answer_text = str(q_data.get("answer_text", "")).strip()
                explanation = str(q_data.get("explanation", "")).strip() or None
                difficulty = str(q_data.get("difficulty", "中等")).strip()
                if difficulty not in self.VALID_DIFFICULTIES:
                    difficulty = "中等"

                # 构建 ORM 对象（暂不 flush）
                question = GeneratedQuestion(
                    courseware_id=kp.courseware_id,
                    knowledge_point_id=kp_id,
                    question_type=question_type_val,
                    question_text=question_text,
                    options=options,
                    answer_text=answer_text,
                    explanation=explanation,
                    source_style="ai_generated",
                    difficulty=difficulty,
                )
                question_models.append(question)

            # 批量写入（原子性：全部成功或全部回滚）
            if question_models:
                self.db.add_all(question_models)
                await self.db.commit()

                # 批量 refresh 以获取 UUID + created_at
                for q in question_models:
                    await self.db.refresh(q)

            # 8. 构建响应并逐个推送
            for q in question_models:
                q_response = {
                    "id": q.id,
                    "courseware_id": q.courseware_id,
                    "knowledge_point_id": q.knowledge_point_id,
                    "question_type": q.question_type,
                    "question_text": q.question_text,
                    "options": q.options,
                    "answer_text": q.answer_text,
                    "explanation": q.explanation,
                    "source_style": q.source_style,
                    "difficulty": q.difficulty,
                    "knowledge_points": [
                        {"id": kp.id, "title": kp.title}
                    ],
                    "created_at": q.created_at.isoformat(),
                }
                question_responses.append(q_response)

                yield _sse_event({
                    "type": "question_parsed",
                    "question": q_response,
                })

            # 9. 发送完成事件
            yield _sse_event({
                "type": "done",
                "questions": question_responses,
                "total": len(question_responses),
            })

            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(
                "题目生成完成: kp_id=%s, 生成 %d 道题, 耗时 %.1fs",
                kp_id,
                len(question_responses),
                elapsed,
            )

        except Exception:
            logger.exception("generate_questions 发生异常 kp_id=%s", kp_id)
            yield _sse_event({
                "type": "error",
                "message": "AI 出题失败，请稍后重试",
            })

    # ── 列表查询 ──────────────────────────────────────

    @staticmethod
    async def list_questions(
        db: AsyncSession,
        courseware_id: str | None = None,
        knowledge_point_id: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """
        分页查询生成的题目列表

        Args:
            db:                 数据库会话
            courseware_id:      按课件筛选（可选）
            knowledge_point_id: 按知识点筛选（可选）
            page:               页码
            size:               每页条数

        Returns:
            {"items": [...], "total": N, "page": P, "size": S, "pages": PAGES}
        """
        conditions = []

        if courseware_id:
            conditions.append(GeneratedQuestion.courseware_id == courseware_id)
        if knowledge_point_id:
            conditions.append(GeneratedQuestion.knowledge_point_id == knowledge_point_id)

        where_clause = and_(*conditions) if conditions else True

        # 总数
        count_result = await db.execute(
            select(func.count(GeneratedQuestion.id)).where(where_clause)
        )
        total = count_result.scalar() or 0

        pages = max(1, math.ceil(total / size)) if total > 0 else 0

        # 分页查询
        offset = (page - 1) * size
        result = await db.execute(
            select(GeneratedQuestion)
            .options(
                selectinload(GeneratedQuestion.knowledge_point),
                selectinload(GeneratedQuestion.courseware),
            )
            .where(where_clause)
            .order_by(desc(GeneratedQuestion.created_at))
            .offset(offset)
            .limit(size)
        )
        questions = list(result.scalars().all())

        items = []
        for q in questions:
            items.append({
                "id": q.id,
                "courseware_id": q.courseware_id,
                "knowledge_point_id": q.knowledge_point_id,
                "question_type": q.question_type,
                "question_text": q.question_text,
                "options": q.options,
                "answer_text": q.answer_text,
                "explanation": q.explanation,
                "source_style": q.source_style,
                "difficulty": q.difficulty,
                "knowledge_points": [
                    {"id": q.knowledge_point.id, "title": q.knowledge_point.title}
                ] if q.knowledge_point else [],
                "courseware_title": q.courseware.title if q.courseware else "",
                "created_at": q.created_at.isoformat(),
            })

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "pages": pages,
        }

    # ── 详情 ──────────────────────────────────────────

    @staticmethod
    async def get_question(db: AsyncSession, question_id: str) -> dict | None:
        """
        获取题目详情（含关联知识点）

        Args:
            db:          数据库会话
            question_id: 题目 ID

        Returns:
            dict 或 None
        """
        result = await db.execute(
            select(GeneratedQuestion)
            .options(
                selectinload(GeneratedQuestion.knowledge_point),
                selectinload(GeneratedQuestion.courseware),
                selectinload(GeneratedQuestion.linked_knowledge_points).selectinload(
                    QuestionKnowledgePoint.knowledge_point
                ),
            )
            .where(GeneratedQuestion.id == question_id)
        )
        q = result.scalar_one_or_none()

        if not q:
            return None

        # 收集所有关联知识点
        linked_kps = [
            {"id": link.knowledge_point.id, "title": link.knowledge_point.title}
            for link in (q.linked_knowledge_points or [])
            if link.knowledge_point
        ]

        # 如果主知识点不在关联列表中，加入
        if q.knowledge_point and not any(
            kp["id"] == q.knowledge_point.id for kp in linked_kps
        ):
            linked_kps.insert(0, {
                "id": q.knowledge_point.id,
                "title": q.knowledge_point.title,
            })

        return {
            "id": q.id,
            "courseware_id": q.courseware_id,
            "knowledge_point_id": q.knowledge_point_id,
            "question_type": q.question_type,
            "question_text": q.question_text,
            "options": q.options,
            "answer_text": q.answer_text,
            "explanation": q.explanation,
            "source_style": q.source_style,
            "difficulty": q.difficulty,
            "knowledge_points": linked_kps,
            "courseware_title": q.courseware.title if q.courseware else "",
            "created_at": q.created_at.isoformat(),
        }

    # ── 删除 ──────────────────────────────────────────

    @staticmethod
    async def delete_question(db: AsyncSession, question_id: str) -> bool:
        """
        删除题目

        Args:
            db:          数据库会话
            question_id: 题目 ID

        Returns:
            True 删除成功，False 题目不存在
        """
        result = await db.execute(
            select(GeneratedQuestion).where(GeneratedQuestion.id == question_id)
        )
        question = result.scalar_one_or_none()

        if not question:
            return False

        await db.delete(question)
        await db.commit()
        return True
