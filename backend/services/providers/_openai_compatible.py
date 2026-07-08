"""
OpenAI 兼容客户端基类

为使用 openai SDK 的提供商（OpenAI, Qwen, DeepSeek 等）提供通用实现。
子类只需覆盖 DEFAULT_BASE_URL 和 SUPPORTED_MODELS 两个类属性即可。

子类约定:
  - DEFAULT_BASE_URL: 默认 API 端点（None 表示使用 openai SDK 内置默认值）
  - SUPPORTED_MODELS: 支持的模型标识符列表
"""

from typing import AsyncIterator

from openai import AsyncOpenAI

from backend.services.ai_client import AbstractAIClient, AIResponse


class OpenAICompatibleClient(AbstractAIClient):
    """
    OpenAI 兼容客户端基类

    封装了基于 openai SDK 的 chat() 和 chat_stream() 通用实现。
    适用于所有提供 OpenAI 兼容 API 的模型服务商（OpenAI 官方、
    阿里云 DashScope、DeepSeek 等）。

    子类只需声明两个类属性:
      - DEFAULT_BASE_URL: 默认 API 端点
      - SUPPORTED_MODELS: 支持的模型列表

    无需覆盖任何方法。
    """

    # 子类必须覆盖此属性
    DEFAULT_BASE_URL: str | None = None

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        # 计算有效 base_url：
        #   优先使用调用者显式传入的 base_url，
        #   其次回退到子类声明的 DEFAULT_BASE_URL
        effective_base_url = base_url or self.DEFAULT_BASE_URL
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=effective_base_url,
        )

        # 创建 AsyncOpenAI 客户端
        #   仅当 self.base_url 非空时才传入 ——
        #   让 openai SDK 在其为 None 时自动使用官方默认端点
        client_kwargs = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        self._client = AsyncOpenAI(**client_kwargs)

    # ── chat ───────────────────────────────────────────
    async def chat(self, messages: list[dict], **kwargs) -> AIResponse:
        """发送消息并获取完整回复（OpenAI 兼容实现）"""
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            **kwargs,
        )

        choice = response.choices[0]
        content = choice.message.content or ""

        return AIResponse(
            content=content,
            usage={
                "prompt_tokens": response.usage.prompt_tokens
                if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens
                if response.usage else 0,
            },
        )

    # ── chat_stream ────────────────────────────────────
    async def chat_stream(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[str]:
        """发送消息并以流式方式逐块返回回复文本（OpenAI 兼容实现）"""
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            stream=True,
            **kwargs,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content
