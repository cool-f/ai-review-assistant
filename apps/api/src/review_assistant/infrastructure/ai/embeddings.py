"""
EmbeddingService — 调用通义千问 DashScope text-embedding-v4 生成文本嵌入向量

特性:
  - 批量嵌入 (batch_size ≤ 25)
  - 单条嵌入快捷方法
  - 自动分批，大列表超出 25 条时自动拆分
  - 支持 document 和 query 两种文本类型
"""

import logging
from math import ceil

import httpx

from review_assistant.core.config import get_settings

logger = logging.getLogger(__name__)

# DashScope 文本嵌入 API 端点
DASHSCOPE_EMBEDDING_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/"
    "embeddings/text-embedding/text-embedding"
)

# 每批最大文本数（DashScope text-embedding-v4 限制为 10）
MAX_BATCH_SIZE = 10

# 请求超时（秒）
REQUEST_TIMEOUT = 60.0


class EmbeddingService:
    """
    文本嵌入服务

    使用阿里云 DashScope text-embedding-v4 模型生成 1024 维向量。

    Usage:
        service = EmbeddingService()
        vectors = await service.embed_batch(["文本1", "文本2"])
        vector = await service.embed_single("单条文本")
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "text-embedding-v4",
    ):
        settings = get_settings()
        self.api_key = api_key or settings.DASHSCOPE_API_KEY
        if not self.api_key:
            raise ValueError(
                "DASHSCOPE_API_KEY 未配置，请在 .env 文件中设置 DASHSCOPE_API_KEY"
            )
        self.model = model
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 httpx 异步客户端（延迟初始化）"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(REQUEST_TIMEOUT),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self) -> None:
        """关闭底层 HTTP 客户端"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── 公开接口 ──────────────────────────────────

    async def embed_batch(
        self,
        texts: list[str],
        text_type: str = "document",
    ) -> list[list[float]]:
        """
        批量生成文本嵌入向量

        自动将输入拆分为 ≤25 条的多批次，按请求顺序合并返回。

        Args:
            texts: 待嵌入的文本列表
            text_type: 文本类型，可选 "document"（文档）或 "query"（查询）

        Returns:
            list[list[float]]: 嵌入向量列表，顺序与输入一致

        Raises:
            ValueError: texts 为空
            RuntimeError: API 调用失败
        """
        if not texts:
            raise ValueError("texts 不能为空")

        # 过滤空字符串（保留索引以便后续对齐）
        valid_indices: list[int] = []
        valid_texts: list[str] = []
        for i, t in enumerate(texts):
            trimmed = t.strip()
            if trimmed:
                valid_indices.append(i)
                valid_texts.append(trimmed)
            else:
                logger.warning("embed_batch: 第 %d 条文本为空，跳过", i)

        if not valid_texts:
            logger.warning("embed_batch: 所有文本均为空，返回零向量列表")
            return [[0.0] * 1024 for _ in texts]

        # 分批
        all_embeddings: list[list[float]] = []
        total_batches = ceil(len(valid_texts) / MAX_BATCH_SIZE)

        for batch_idx in range(total_batches):
            start = batch_idx * MAX_BATCH_SIZE
            end = min(start + MAX_BATCH_SIZE, len(valid_texts))
            batch_texts = valid_texts[start:end]

            logger.debug(
                "嵌入批次 %d/%d: %d 条文本",
                batch_idx + 1,
                total_batches,
                len(batch_texts),
            )

            try:
                batch_embeddings = await self._call_api(batch_texts, text_type)
                all_embeddings.extend(batch_embeddings)
            except Exception as exc:
                raise RuntimeError(
                    f"嵌入批次 {batch_idx + 1}/{total_batches} 失败: {exc}"
                ) from exc

        # 按原始顺序重新排列（插入空文本的零向量）
        result: list[list[float]] = []
        valid_cursor = 0
        for i in range(len(texts)):
            if i in valid_indices:
                result.append(all_embeddings[valid_cursor])
                valid_cursor += 1
            else:
                result.append([0.0] * 1024)

        return result

    async def embed_single(
        self,
        text: str,
        text_type: str = "document",
    ) -> list[float]:
        """
        为单条文本生成嵌入向量

        Args:
            text: 待嵌入的文本
            text_type: 文本类型，可选 "document" 或 "query"

        Returns:
            list[float]: 1024 维嵌入向量

        Raises:
            RuntimeError: API 调用失败
        """
        results = await self.embed_batch([text], text_type=text_type)
        return results[0]

    # ── 内部 ──────────────────────────────────────

    async def _call_api(
        self,
        texts: list[str],
        text_type: str,
    ) -> list[list[float]]:
        """
        调用 DashScope text-embedding API

        Args:
            texts: 文本列表（已确保 ≤ MAX_BATCH_SIZE）
            text_type: "document" 或 "query"

        Returns:
            list[list[float]]: 与输入顺序一致的嵌入向量列表
        """
        from review_assistant.infrastructure.usage.context import current_usage_context
        from review_assistant.infrastructure.usage.token_counter import ensure_budget, record_usage

        await ensure_budget()
        if len(texts) > MAX_BATCH_SIZE:
            raise ValueError(
                f"单次 API 调用最多 {MAX_BATCH_SIZE} 条文本，收到 {len(texts)} 条"
            )

        payload = {
            "model": self.model,
            "input": {
                "texts": texts,
            },
            "parameters": {
                "text_type": text_type,
            },
        }

        client = await self._get_client()

        response = await client.post(DASHSCOPE_EMBEDDING_URL, json=payload)

        if response.status_code != 200:
            error_detail = response.text
            try:
                error_json = response.json()
                error_detail = error_json.get("message", error_detail)
            except Exception:
                pass
            raise RuntimeError(
                f"DashScope 嵌入 API 返回 {response.status_code}: {error_detail}"
            )

        data = response.json()

        # 检查是否有错误
        if "code" in data and data.get("code") != "":
            raise RuntimeError(
                f"DashScope 嵌入 API 错误: code={data.get('code')}, "
                f"message={data.get('message', 'unknown')}"
            )

        # 提取嵌入向量
        output = data.get("output", {})
        embeddings_raw = output.get("embeddings", [])

        if not embeddings_raw:
            raise RuntimeError(
                f"DashScope 嵌入 API 返回空嵌入结果。响应: {str(data)[:500]}"
            )

        # 按 text_index 排序，确保顺序一致
        embeddings_raw.sort(key=lambda x: x.get("text_index", 0))

        result = [item["embedding"] for item in embeddings_raw]

        count_mismatch = len(result) != len(texts)

        logger.debug(
            "嵌入成功: %d 条文本 -> %d 个向量 (维度: %d)",
            len(texts),
            len(result),
            len(result[0]) if result else 0,
        )

        context = current_usage_context()
        await record_usage(
            provider="dashscope",
            model=self.model,
            prompt_tokens=sum(max(1, len(value) // 3) for value in texts),
            completion_tokens=0,
            course_id=context.course_id,
            session_id=context.session_id,
            purpose=context.purpose if context.purpose != "unspecified" else "embedding",
        )
        if count_mismatch:
            raise RuntimeError(
                f"嵌入返回数量与输入不匹配: 期望 {len(texts)}, 实际 {len(result)}"
            )
        return result
