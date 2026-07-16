import asyncio

import pytest

from review_assistant.infrastructure.ai.embeddings import EmbeddingService
from review_assistant.infrastructure.usage import token_counter


class _Response:
    status_code = 200

    def json(self):
        return {
            "output": {
                "embeddings": [
                    {"text_index": 0, "embedding": [0.0] * 1024},
                ]
            }
        }


class _Client:
    async def post(self, url, json):
        return _Response()


class _PartialEmbeddingService(EmbeddingService):
    def __init__(self):
        self.model = "test-model"
        self._client = _Client()


def test_partial_embedding_response_is_a_failure(monkeypatch):
    async def ensure_budget():
        return None

    async def record_usage(**kwargs):
        return None

    monkeypatch.setattr(token_counter, "ensure_budget", ensure_budget)
    monkeypatch.setattr(token_counter, "record_usage", record_usage)

    with pytest.raises(RuntimeError, match="数量与输入不匹配"):
        asyncio.run(_PartialEmbeddingService()._call_api(
            ["first", "second"], text_type="document"
        ))
