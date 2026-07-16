"""
HomeworkService — 作业文本处理、AI 解答 (SSE 流式)、批量并行解答

提供:
  - extract_questions(full_text)        — 题目识别与切分
  - solve_question(question_text, ...)  — 单题 AI 流式解答 (异步生成器)
  - batch_solve(homework_id)           — 并行解答 (最多 3 题) + 知识点匹配
"""

import asyncio
import json
import logging
import re

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from review_assistant.infrastructure.persistence.database import async_session_factory
from review_assistant.infrastructure.persistence.models import Homework, Solution, SolutionKnowledgePoint
from review_assistant.infrastructure.ai.client import get_ai_client, AbstractAIClient
from review_assistant.application.homework.matcher import KPMatcher
from review_assistant.application.homework.concurrency import (
    cancel_and_wait,
    drain_until_sentinel,
    interrupted_homework_status,
)
from review_assistant.infrastructure.usage.context import usage_scope


logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# 题目识别正则
# ═══════════════════════════════════════════════════════

# 匹配题号模式:
#   \d+[\.\).、]\s*      — "1.", "1)", "1、", "1. "
#   第[一二三四五六七八九十百千\d]+题  — "第一题" / "第1题"
_QUESTION_PATTERN = re.compile(
    r'(?:^|\n)\s*('
    r'\d+[\.\).、]\s*'
    r'|'
    r'第[一二三四五六七八九十百千\d]+题\s*'
    r')',
    re.MULTILINE,
)


# ═══════════════════════════════════════════════════════
# AI 解答系统提示词
# ═══════════════════════════════════════════════════════

SOLVE_SYSTEM_PROMPT = """你是一位专业的学科辅导老师。你的任务是解答学生提交的作业题目。

## 要求

1. **逐步推导**: 展示完整的解题思路和步骤，不要只给出最终答案。
2. **解释原理**: 在关键步骤说明所依据的原理、定理或公式，帮助学生理解。
3. **清晰格式**: 使用 Markdown 组织解答，善用标题、列表、公式（LaTeX 风格）。
4. **答案明确**: 在解答末尾用 **「答案」** 标注最终结果。
5. **语言一致**: 使用与题目相同的语言作答。

## 注意事项

- 如果题目信息不完整，先说明缺少的信息，再给出合理假设继续解答。
- 对于选择题，不仅要给正确答案，还要解释为什么其他选项不正确。
- 对于证明题，展现严密的逻辑推导过程。
- 对于计算题，写出每一步的计算式和中间结果。"""


# ═══════════════════════════════════════════════════════
# SSE 工具
# ═══════════════════════════════════════════════════════

def _sse_event(data: dict) -> str:
    """将字典序列化为 SSE data 行"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ═══════════════════════════════════════════════════════
# HomeworkService
# ═══════════════════════════════════════════════════════

class HomeworkService:
    """
    作业业务逻辑

    职责:
      - 从作业全文中识别并切分题目
      - 调用 AI 客户端流式解答单个题目
      - 并行批量解答 (最多 3 个并发 AI 请求)
      - 解答完成后自动匹配已有知识点
    """

    # 并行解答最大并发数
    MAX_CONCURRENT_SOLVES = 3

    def __init__(self, db: AsyncSession):
        """
        Args:
            db: 数据库会话 (用于查询作业、保存结果等)
        """
        self.db = db
        self._ai_client: AbstractAIClient | None = None

    @property
    def ai_client(self) -> AbstractAIClient:
        """延迟初始化 AI 客户端 (避免 import 时读取配置失败)"""
        if self._ai_client is None:
            self._ai_client = get_ai_client()
        return self._ai_client

    # ── 题目识别 ──────────────────────────────────

    @staticmethod
    def extract_questions(full_text: str) -> list[dict]:
        """
        从作业全文中识别并切分题目

        识别模式:
          - 数字编号: "1.", "1)", "1、", "1. "
          - 中文编号: "第一题", "第1题"

        切分策略:
          1. 查找所有题号匹配位置
          2. 在匹配起始处切割
          3. 两个匹配之间的文本属于前一个题目
          4. 若全文无匹配，整个文本视为 1 道题

        Args:
            full_text: 作业全文

        Returns:
            [{"question_number": int, "question_text": str}, ...]
        """
        if not full_text or not full_text.strip():
            return []

        matches = list(_QUESTION_PATTERN.finditer(full_text))

        if not matches:
            # 没有识别到题号，整文作为一道题
            return [{"question_number": 1, "question_text": full_text.strip()}]

        questions: list[dict] = []
        for i, match in enumerate(matches):
            start = match.start()
            # 跳过题号前的换行符，让题目文本更干净
            # match 可能匹配了开头的 \n，需要调整起始位置
            matched_text = match.group(0)
            if matched_text.startswith("\n"):
                start = start + 1

            if i + 1 < len(matches):
                end = matches[i + 1].start()
            else:
                end = len(full_text)

            question_text = full_text[start:end].strip()
            if question_text:
                questions.append({
                    "question_number": i + 1,
                    "question_text": question_text,
                })

        return questions

    # ── 单题流式解答 ──────────────────────────────

    async def solve_question(
        self,
        question_text: str,
        question_number: int,
        temperature: float = 0.3,
    ):
        """
        对单道题进行 AI 流式解答 (异步生成器)

        每个 yield 输出一条 SSE 格式的字符串:
          data: {"type":"token","question_number":N,"content":"..."}\n\n

        Args:
            question_text:   题目文本
            question_number: 题号
            temperature:     AI 温度参数 (解答建议偏低以保证准确性)

        Yields:
            SSE 格式字符串
        """
        messages = [
            {"role": "system", "content": SOLVE_SYSTEM_PROMPT},
            {"role": "user", "content": f"请解答以下题目：\n\n{question_text}"},
        ]

        try:
            with usage_scope("homework_solve"):
                async for chunk in self.ai_client.chat_stream(
                    messages,
                    temperature=temperature,
                ):
                    yield _sse_event({
                        "type": "token",
                        "question_number": question_number,
                        "content": chunk,
                    })
        except Exception as exc:
            logger.exception(
                "solve_question 失败: question_number=%d", question_number
            )
            yield _sse_event({
                "type": "error",
                "question_number": question_number,
                "message": f"AI 解答失败: {str(exc)}",
            })

    # ── 批量并行解答 ──────────────────────────────

    async def batch_solve(self, homework_id: str):
        """
        批量并行解答作业中所有未解答的题目

        流程:
          1. 查询所有 answer_text 为空的 Solution
          2. 使用 asyncio.Semaphore(3) 控制最大并行 AI 请求数
          3. 每个解答任务将 AI 流式输出合并到统一 SSE 流中
          4. 解答完成后自动保存到数据库
          5. 全部完成后触发知识点匹配 (KPMatcher)

        SSE 事件类型:
          - token:          AI 增量文本 (含 question_number)
          - question_done:  单题解答完成
          - question_error: 单题解答失败
          - match_result:   知识点匹配结果
          - done:           全部完成

        Yields:
            SSE 格式字符串
        """
        # ── 1. 查询未解答的题目 ──────────────────
        result = await self.db.execute(
            select(Solution)
            .where(
                Solution.homework_id == homework_id,
                Solution.answer_text.is_(None),
            )
            .order_by(Solution.question_number)
        )
        unsolved = list(result.scalars().all())

        if not unsolved:
            await self._update_homework_status(homework_id, "completed", None)
            yield _sse_event({
                "type": "done",
                "message": "所有题目已解答完毕",
                "homework_id": homework_id,
            })
            return

        logger.info(
            "开始批量解答: homework_id=%s, 未解题目数=%d",
            homework_id,
            len(unsolved),
        )

        # ── 更新作业状态为 processing ────────────
        hw_result = await self.db.execute(
            select(Homework).where(Homework.id == homework_id)
        )
        homework = hw_result.scalar_one_or_none()
        if homework:
            homework.status = "processing"
            homework.error_message = None
            await self.db.commit()

        completed_normally = False
        tasks: list[asyncio.Task] = []
        try:
            # ── 2. 设置并发控制 ────────────────────
            queue: asyncio.Queue[str | None] = asyncio.Queue()
            semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_SOLVES)
            total = len(unsolved)
            finished_count = 0
            failed_count = 0
            finish_lock = asyncio.Lock()

            async def _solve_one(sol: Solution) -> None:
                """在一个独立 DB 会话中解答单题并持久化"""
                nonlocal failed_count, finished_count

                async with semaphore:
                    answer_parts: list[str] = []

                    try:
                        messages = [
                            {"role": "system", "content": SOLVE_SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": f"请解答以下题目：\n\n{sol.question_text}",
                            },
                        ]

                        with usage_scope("homework_solve", course_id=homework.course_id if homework else None):
                            async for chunk in self.ai_client.chat_stream(
                                messages,
                                temperature=0.3,
                            ):
                                answer_parts.append(chunk)
                                await queue.put(_sse_event({
                                    "type": "token",
                                    "question_number": sol.question_number,
                                    "content": chunk,
                                }))

                        full_answer = "".join(answer_parts)

                        # 持久化解答 (使用独立会话)
                        async with async_session_factory() as solver_db:
                            s_result = await solver_db.execute(
                                select(Solution).where(Solution.id == sol.id)
                            )
                            sol_in_db = s_result.scalar_one()
                            sol_in_db.answer_text = full_answer
                            await solver_db.commit()

                        await queue.put(_sse_event({
                            "type": "question_done",
                            "question_number": sol.question_number,
                            "solution_id": sol.id,
                        }))

                    except Exception as exc:
                        failed_count += 1
                        logger.exception(
                            "解答失败: homework_id=%s, question_number=%d",
                            homework_id,
                            sol.question_number,
                        )
                        await queue.put(_sse_event({
                            "type": "question_error",
                            "question_number": sol.question_number,
                            "solution_id": sol.id,
                            "message": str(exc),
                        }))

                    finally:
                        async with finish_lock:
                            nonlocal finished_count
                            finished_count += 1
                            if finished_count >= total:
                                await queue.put(None)  # 全部完成的哨兵

            # ── 3. 启动并行解答任务 ─────────────────
            tasks = [
                asyncio.create_task(_solve_one(sol))
                for sol in unsolved
            ]

            # ── 4. 从共享队列中消费 SSE 事件 ─────────
            async for event in drain_until_sentinel(queue):
                yield event

            # 等待所有任务完成
            await asyncio.gather(*tasks, return_exceptions=True)

            # ── 5. 知识点匹配 ─────────────────────
            # 重新查询已解答的题目
            await self.db.refresh(homework) if homework else None
            result = await self.db.execute(
                select(Solution)
                .where(
                    Solution.homework_id == homework_id,
                    Solution.answer_text.isnot(None),
                )
                .order_by(Solution.question_number)
            )
            solved = list(result.scalars().all())

            if solved:
                async for match_event in self._match_and_link(
                    solved, course_id=homework.course_id if homework else ""
                ):
                    yield match_event

            # ── 6. 更新作业状态 ───────────────────
            if homework:
                # 可能事务已失效，使用新会话
                try:
                    homework.status = "partial" if failed_count else "completed"
                    homework.error_message = (
                        f"{failed_count} 道题解答失败，可再次点击继续解题"
                        if failed_count else None
                    )
                    await self.db.commit()
                except Exception:
                    await self._update_homework_status(
                        homework_id,
                        "partial" if failed_count else "completed",
                        f"{failed_count} 道题解答失败，可重试" if failed_count else None,
                    )

            yield _sse_event({
                "type": "done",
                "homework_id": homework_id,
                "solved_count": len(solved),
                "failed_count": failed_count,
            })

            completed_normally = True

        finally:
            if not completed_normally:
                # Wait for every solver to stop before reconciling durable state;
                # otherwise a late per-question commit can race the status write.
                await cancel_and_wait(tasks)
                logger.warning(
                    "解答过程被中断 (SSE 连接断开): homework_id=%s, 正在恢复状态",
                    homework_id,
                )
                await self.reconcile_interrupted_homework(homework_id)

    # ── 知识点匹配与关联 ──────────────────────────

    async def _match_and_link(
        self, solutions: list[Solution], course_id: str
    ):
        """
        对已解答的每条 Solution 运行 KPMatcher 并创建关联记录

        幂等设计:
          - 先删除所有旧链接，再写入新链接
          - 所有写入在单次 commit 中完成，避免部分持久化
          - 重复调用 /solve 不会触发唯一约束冲突

        Yields:
            SSE match_result 事件
        """
        matcher = KPMatcher(self.db)

        # ── 先删除旧链接，保证幂等 ──────────────
        if solutions:
            solution_ids = [s.id for s in solutions]
            await self.db.execute(
                delete(SolutionKnowledgePoint).where(
                    SolutionKnowledgePoint.solution_id.in_(solution_ids)
                )
            )

        # ── 逐题匹配，暂存链接 ────────────────────
        for sol in solutions:
            # 组合题目 + 答案作为匹配文本
            combined_text = f"{sol.question_text}\n{sol.answer_text or ''}"

            try:
                with usage_scope("homework_matching", course_id=course_id):
                    matches = await matcher.match(combined_text, course_id=course_id)

                # 写入关联记录 (暂不提交，收集完成后一次性 commit)
                for m in matches:
                    link = SolutionKnowledgePoint(
                        solution_id=sol.id,
                        knowledge_point_id=m["knowledge_point_id"],
                        relevance_score=m["relevance_score"],
                        match_method=m["match_method"],
                    )
                    self.db.add(link)

                yield _sse_event({
                    "type": "match_result",
                    "solution_id": sol.id,
                    "question_number": sol.question_number,
                    "matches": [
                        {
                            "knowledge_point_id": m["knowledge_point_id"],
                            "title": m["title"],
                            "relevance_score": m["relevance_score"],
                            "match_method": m["match_method"],
                        }
                        for m in matches
                    ],
                })

            except Exception as exc:
                logger.exception(
                    "知识点匹配失败: solution_id=%s", sol.id
                )
                yield _sse_event({
                    "type": "match_error",
                    "solution_id": sol.id,
                    "question_number": sol.question_number,
                    "message": str(exc),
                })
                # 不在此处回滚：单题匹配失败不中断其他题目，
                # 最终 commit 时统一提交所有成功题目 + 旧链接删除

        # ── 一次性提交所有链接 ────────────────────
        try:
            await self.db.commit()
        except Exception as exc:
            logger.exception("知识点关联批量写入失败，执行回滚")
            await self.db.rollback()
            raise

    # ── 辅助方法 ──────────────────────────────────

    async def _update_homework_status(
        self,
        homework_id: str,
        status: str,
        error_message: str | None,
    ) -> None:
        """使用新会话更新作业状态"""
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(Homework).where(Homework.id == homework_id)
                )
                hw = result.scalar_one_or_none()
                if hw:
                    hw.status = status
                    hw.error_message = error_message
                    await db.commit()
        except Exception as exc:
            logger.error("更新作业状态失败: %s", exc)

    async def reconcile_interrupted_homework(self, homework_id: str) -> None:
        """Derive terminal state from answers committed before interruption."""
        try:
            async with async_session_factory() as db:
                total, answered = (await db.execute(
                    select(
                        func.count(Solution.id),
                        func.count(Solution.answer_text),
                    ).where(Solution.homework_id == homework_id)
                )).one()
                status = interrupted_homework_status(int(total), int(answered))
                homework = await db.get(Homework, homework_id)
                if homework is None:
                    return
                homework.status = status
                homework.error_message = (
                    None
                    if status == "completed"
                    else "SSE连接中断；已保存的答案保留，可继续未完成题目"
                )
                await db.commit()
        except Exception as exc:
            logger.error("恢复中断作业状态失败: %s", exc)
