"""
通义千问 (Qwen) 提供商

通过阿里云 DashScope 的 OpenAI 兼容接口调用通义千问模型。

DashScope OpenAI 兼容端点:
    https://dashscope.aliyuncs.com/compatible-mode/v1

API Key 获取: https://dashscope.console.aliyun.com/apiKey
"""

from backend.services.providers._openai_compatible import OpenAICompatibleClient


class QwenClient(OpenAICompatibleClient):
    """通义千问客户端（DashScope OpenAI 兼容模式）"""

    DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    SUPPORTED_MODELS = [
        "qwen-turbo",
        "qwen-plus",
        "qwen-max",
        "qwen-max-longcontext",
    ]
