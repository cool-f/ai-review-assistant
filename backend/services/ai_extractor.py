"""
AIExtractor — 调用 AI 从课件全文中提取知识点和例题

流程:
  1. 构造 system prompt，要求输出结构化 JSON
  2. 调用 AI 客户端（通过 ai_client 工厂）获取响应
  3. 解析 JSON（含正则 fallback）
  4. 失败时重试 1 次（间隔 2 秒）
"""

import asyncio
import json
import logging
import re

from backend.services.ai_client import AIMessage, AbstractAIClient, get_ai_client

logger = logging.getLogger(__name__)

# 单次提取的最大文本长度（字符），超出则截断
MAX_EXTRACTION_TEXT_LENGTH = 80_000

EXTRACTION_SYSTEM_PROMPT = """你是一位专业的教育领域知识提取专家。你的任务是从课件文本中提取出所有的知识点和对应的例题。

## 输出要求

你必须输出一个严格合法的 JSON 对象，格式如下：

```json
{
  "knowledge_points": [
    {
      "name": "知识点名称（简洁明确）",
      "summary": "知识点的详细内容摘要，包含核心概念、定义、公式、定理等（200-500字）",
      "difficulty": "简单 | 中等 | 困难",
      "page_ref": 页码数字（如果文本中没有页码信息则为 null）,
      "examples": [
        {
          "question": "例题题目原文",
          "answer": "例题答案",
          "explanation": "解题思路和步骤说明（可以为空字符串）"
        }
      ]
    }
  ]
}
```

## 提取规则

1. **知识点粒度**：每个知识点应该是一个独立、完整的教学单元（如一个概念、一个定理、一个公式）
2. **不要遗漏**：覆盖课件中所有出现的知识点，即使是简要提及的也要提取
3. **例题归属**：将例题归属到最相关的知识点下；如果例题涉及多个知识点，归到最核心的那个
4. **难度评估**：根据知识点的复杂度、是否为基础概念、是否需要前置知识来判断难度
   - 简单：基础概念、定义类
   - 中等：需要理解和应用的定理、方法类
   - 困难：复杂推导、综合应用类
5. **摘要质量**：摘要应包含知识点的核心内容，让没有看过课件的人也能理解
6. **语言**：输出语言与课件原文语言保持一致（中文课件输出中文，英文课件输出英文）

## 重要

- 只输出 JSON，不要有任何额外的解释或前言
- 如果课件中没有找到任何知识点，返回 `{"knowledge_points": []}`
- 确保 JSON 是合法的，所有字符串都正确转义"""


class AIExtractor:
    """AI 知识点提取器"""

    @staticmethod
    async def extract_knowledge_points(
        full_text: str,
        max_retries: int = 1,
        ai_client: AbstractAIClient | None = None,
    ) -> dict:
        """
        从课件全文中提取知识点和例题

        Args:
            full_text: 课件提取出的纯文本
            max_retries: 最大重试次数（默认 1 次，即总共尝试 1+1=2 次）
            ai_client: 可选的 AI 客户端实例（用于测试 mock 注入）。
                       传入时使用传入实例，否则回退到 get_ai_client() 工厂。

        Returns:
            dict: 包含 knowledge_points 数组的字典
                格式: {"knowledge_points": [{name, summary, difficulty, page_ref, examples}, ...]}

        Raises:
            RuntimeError: 所有重试均失败
        """
        # 截断过长文本，保护 LLM 上下文窗口
        text = full_text
        if len(text) > MAX_EXTRACTION_TEXT_LENGTH:
            logger.warning(
                "课件文本过长 (%d 字符)，截断至 %d 字符",
                len(text),
                MAX_EXTRACTION_TEXT_LENGTH,
            )
            text = text[:MAX_EXTRACTION_TEXT_LENGTH] + "\n\n[文本因过长已截断]"

        messages = [
            AIMessage(role="system", content=EXTRACTION_SYSTEM_PROMPT).to_dict(),
            AIMessage(
                role="user",
                content=f"请从以下课件文本中提取所有知识点和例题：\n\n{text}",
            ).to_dict(),
        ]

        last_error: Exception | None = None

        for attempt in range(max_retries + 1):  # 1 次初始 + max_retries 次重试
            try:
                if attempt > 0:
                    logger.info("AI 提取重试 %d/%d", attempt, max_retries)
                    await asyncio.sleep(2)

                client = ai_client or get_ai_client()
                response = await client.chat(
                    messages=messages,
                    temperature=0.3,  # 低温度提高输出稳定性
                    max_tokens=16384,  # 高配额确保完整 JSON 输出不被截断
                )

                raw_text = response.content.strip()
                logger.debug("AI 原始响应长度: %d 字符", len(raw_text))

                result = AIExtractor._parse_json_response(raw_text)

                # 验证结果结构
                if "knowledge_points" not in result:
                    raise ValueError("响应 JSON 中缺少 'knowledge_points' 字段")

                kps = result["knowledge_points"]
                if not isinstance(kps, list):
                    raise ValueError(
                        f"'knowledge_points' 应为列表，实际为 {type(kps).__name__}"
                    )

                # 规范化每个知识点条目
                normalized_kps = []
                for i, kp in enumerate(kps):
                    if not isinstance(kp, dict):
                        logger.warning("跳过非字典类型的知识点条目: %s", type(kp).__name__)
                        continue

                    normalized = {
                        "name": str(kp.get("name", f"知识点 {i+1}")).strip(),
                        "summary": str(kp.get("summary", "")).strip(),
                        "difficulty": str(kp.get("difficulty", "中等")).strip(),
                        "page_ref": kp.get("page_ref"),
                        "examples": [],
                    }

                    # 规范化 page_ref
                    if normalized["page_ref"] is not None:
                        try:
                            normalized["page_ref"] = int(normalized["page_ref"])
                        except (ValueError, TypeError):
                            normalized["page_ref"] = None

                    # 规范化 difficulty
                    if normalized["difficulty"] not in ("简单", "中等", "困难", "easy", "medium", "hard"):
                        normalized["difficulty"] = "中等"

                    # 规范化 examples
                    raw_examples = kp.get("examples", [])
                    if isinstance(raw_examples, list):
                        for ex in raw_examples:
                            if isinstance(ex, dict):
                                example = {
                                    "question": str(ex.get("question", "")).strip(),
                                    "answer": str(ex.get("answer", "")).strip(),
                                    "explanation": str(ex.get("explanation", "")).strip(),
                                }
                                if example["question"]:  # 只保留有题目的例题
                                    normalized["examples"].append(example)

                    normalized_kps.append(normalized)

                result["knowledge_points"] = normalized_kps
                logger.info(
                    "AI 提取成功: %d 个知识点 (尝试 %d 次)",
                    len(normalized_kps),
                    attempt + 1,
                )
                return result

            except Exception as exc:
                last_error = exc
                logger.warning(
                    "AI 提取失败 (尝试 %d/%d): %s",
                    attempt + 1,
                    max_retries + 1,
                    str(exc),
                )

        raise RuntimeError(
            f"AI 知识点提取在 {max_retries + 1} 次尝试后仍然失败: {last_error}"
        )

    @staticmethod
    def _parse_json_response(raw_text: str) -> dict:
        """
        解析 AI 响应中的 JSON，含多层 fallback

        策略:
          1. 直接 json.loads 整个文本
          2. 正则匹配 ```json ... ``` 代码块
          3. 正则匹配 ``` ... ``` 代码块
          4. 正则匹配最外层 {...} 对象

        Args:
            raw_text: AI 返回的原始文本

        Returns:
            dict: 解析后的 JSON 对象

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

        # 策略 4: 匹配最外层 {...}
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
