import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import requests

from app.services.config_service import ConfigService


def test_openai_provider_test_uses_newapi_endpoint(monkeypatch):
    """OpenAI 厂家测试应请求指定的 OpenAI 兼容网关。"""
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            status_code=200,
            headers={"Content-Type": "application/json"},
            json=lambda: {"choices": [{"message": {"content": "OK"}}]},
        )

    monkeypatch.setattr(requests, "post", fake_post)

    result = ConfigService()._test_openai_api("test-key", "OpenAI")

    assert result["success"] is True
    assert captured["url"] == "https://newapi.1234bot.com/v1/responses"
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer test-key"
    assert captured["kwargs"]["json"]["model"] == "gpt-5.6-sol"
    assert captured["kwargs"]["json"]["stream"] is False


def test_openai_provider_test_uses_configured_model(monkeypatch):
    """OpenAI 厂家测试应优先使用传入的厂家测试模型。"""
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            status_code=200,
            headers={"Content-Type": "application/json"},
            json=lambda: {"choices": [{"message": {"content": "OK"}}]},
        )

    monkeypatch.setattr(requests, "post", fake_post)

    result = ConfigService()._test_openai_api("test-key", "OpenAI", "gpt-4o-mini")

    assert result["success"] is True
    assert captured["kwargs"]["json"]["model"] == "gpt-4o-mini"


def test_openai_provider_connection_passes_provider_test_model(monkeypatch):
    """厂家连接测试应把数据库中的 test_model 传给 OpenAI 测试函数。"""
    captured = {}

    async def fake_get_db(self):
        collection = MagicMock()
        collection.find_one = AsyncMock(
            return_value={
                "name": "openai",
                "default_base_url": "https://newapi.1234bot.com/v1",
                "test_model": "gpt-5.6-sol",
            }
        )
        return SimpleNamespace(llm_providers=collection)

    def fake_test_openai_api(self, api_key, display_name, test_model=None):
        captured["api_key"] = api_key
        captured["display_name"] = display_name
        captured["test_model"] = test_model
        return {"success": True, "message": "ok"}

    monkeypatch.setattr(ConfigService, "_get_db", fake_get_db)
    monkeypatch.setattr(ConfigService, "_test_openai_api", fake_test_openai_api)

    result = asyncio.run(
        ConfigService()._test_provider_connection("openai", "test-key", "OpenAI")
    )

    assert result["success"] is True
    assert captured["api_key"] == "test-key"
    assert captured["display_name"] == "OpenAI"
    assert captured["test_model"] == "gpt-5.6-sol"


def test_openai_provider_test_accepts_responses_api_sse(monkeypatch):
    """Responses API 返回 SSE 时，厂家测试应从事件中提取文本。"""

    sse_body = (
        'event: response.output_text.done\n'
        'data: {"type":"response.output_text.done","text":"pong"}\n\n'
        'event: response.completed\n'
        'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
    )

    def fake_post(url, **kwargs):
        return SimpleNamespace(
            status_code=200,
            headers={"Content-Type": "text/event-stream"},
            text=sse_body,
            json=lambda: (_ for _ in ()).throw(ValueError("not JSON")),
        )

    monkeypatch.setattr(requests, "post", fake_post)

    result = ConfigService()._test_openai_api("test-key", "OpenAI")

    assert result["success"] is True


def test_openai_provider_test_falls_back_when_model_at_capacity(monkeypatch):
    """首选模型满负载时，应自动尝试备用模型。"""
    models = []

    def fake_post(url, **kwargs):
        models.append(kwargs["json"]["model"])
        if len(models) == 1:
            return SimpleNamespace(
                status_code=503,
                headers={"Content-Type": "application/json"},
                text="Selected model is at capacity",
                json=lambda: {"error": {"message": "Selected model is at capacity"}},
            )
        return SimpleNamespace(
            status_code=200,
            headers={"Content-Type": "application/json"},
            text='{"output_text":"OK"}',
            json=lambda: {"output_text": "OK"},
        )

    monkeypatch.setattr(requests, "post", fake_post)

    result = ConfigService()._test_openai_api("test-key", "OpenAI", "gpt-5.6-sol")

    assert result["success"] is True
    assert models == ["gpt-5.6-sol", "gpt-5.6-terra"]


def test_openai_provider_test_falls_back_when_request_times_out(monkeypatch):
    """备用模型请求超时后，应继续尝试下一个模型。"""
    models = []

    def fake_post(url, **kwargs):
        models.append(kwargs["json"]["model"])
        if len(models) < 3:
            raise requests.Timeout("gateway timeout")
        return SimpleNamespace(
            status_code=200,
            headers={"Content-Type": "application/json"},
            text='{"output_text":"OK"}',
            json=lambda: {"output_text": "OK"},
        )

    monkeypatch.setattr(requests, "post", fake_post)

    result = ConfigService()._test_openai_api("test-key", "OpenAI", "gpt-5.6-sol")

    assert result["success"] is True
    assert models == [
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "google/gemini-3.5-flash-lite",
    ]
