"""
Anthropic (Claude) 提供商

使用 anthropic SDK 调用 Claude 系列模型。
内部将 OpenAI 兼容的 messages 格式转换为 Anthropic 原生格式：
  - system 角色消息提取为独立的 system 参数
  - user / assistant 消息保留在 messages 列表中
"""

from typing import AsyncIterator

from anthropic import AsyncAnthropic

from review_assistant.infrastructure.ai.client import AbstractAIClient, AIResponse


class AnthropicClient(AbstractAIClient):
    """Anthropic Claude 客户端"""

    SUPPORTED_MODELS = [
        "claude-opus-4-20250514",
        "claude-sonnet-4-20250514",
        "claude-3-5-haiku-20241022",
    ]

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        super().__init__(api_key=api_key, model=model, base_url=base_url)
        client_kwargs = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        self._client = AsyncAnthropic(**client_kwargs)

    # ── 格式转换 ────────────────────────────────────────
    @staticmethod
    def _extract_system_prompt(messages: list[dict]) -> str | None:
        """从 messages 中提取 system 角色的内容"""
        system_msgs = [m for m in messages if m.get("role") == "system"]
        if not system_msgs:
            return None
        return "\n\n".join(m["content"] for m in system_msgs)

    @staticmethod
    def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
        """
        将 OpenAI 格式的消息列表转为 Anthropic 格式。
        Anthropic 要求 messages 不能包含 system 角色，
        且 content 可以是纯字符串或 content block 列表。
        """
        result: list[dict] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")

            if role == "system":
                # system 消息由 _extract_system_prompt 处理，这里跳过
                continue

            if isinstance(content, list):
                # content 为 OpenAI content blocks 格式（多模态）
                anthropic_content = []
                for block in content:
                    block_type = block.get("type", "")
                    if block_type == "text":
                        anthropic_content.append(
                            {"type": "text", "text": block.get("text", "")}
                        )
                    elif block_type == "image_url":
                        url = block.get("image_url", {}).get("url", "")
                        if url.startswith("data:image/"):
                            media_type = url.split(";")[0].replace("data:", "")
                            base64_data = (
                                url.split(",")[1] if "," in url else url
                            )
                            anthropic_content.append(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": base64_data,
                                    },
                                }
                            )
                result.append({"role": "user", "content": anthropic_content})
            elif role == "assistant":
                result.append({"role": "assistant", "content": content})
            else:
                # user（以及其他角色，归一化为 user）
                result.append({"role": "user", "content": content})

        return result

    # ── chat ───────────────────────────────────────────
    async def chat(self, messages: list[dict], **kwargs) -> AIResponse:
        system_prompt = self._extract_system_prompt(messages)
        anthropic_messages = self._to_anthropic_messages(messages)

        # Anthropic 要求 max_tokens，给出合理默认值
        max_tokens = kwargs.pop("max_tokens", 4096)

        create_kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": anthropic_messages,
        }
        if system_prompt:
            create_kwargs["system"] = system_prompt
        create_kwargs.update(kwargs)

        response = await self._client.messages.create(**create_kwargs)

        content_text = ""
        for block in response.content:
            if block.type == "text":
                content_text += block.text

        return AIResponse(
            content=content_text,
            usage={
                "prompt_tokens": response.usage.input_tokens
                if response.usage else 0,
                "completion_tokens": response.usage.output_tokens
                if response.usage else 0,
            },
        )

    # ── chat_stream ────────────────────────────────────
    async def chat_stream(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[str]:
        system_prompt = self._extract_system_prompt(messages)
        anthropic_messages = self._to_anthropic_messages(messages)

        max_tokens = kwargs.pop("max_tokens", 4096)

        stream_kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": anthropic_messages,
        }
        if system_prompt:
            stream_kwargs["system"] = system_prompt
        stream_kwargs.update(kwargs)

        async with self._client.messages.stream(**stream_kwargs) as stream:
            async for text in stream.text_stream:
                yield text
