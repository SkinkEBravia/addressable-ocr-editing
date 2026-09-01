"""openai-completion 适配器的 golden 测试（录制响应回放，不打真实端点）。"""

from __future__ import annotations

import httpx
import pytest

from llm import Message, ModelConfig
from llm.adapters.openai_completion import OpenAICompletionClient
from llm.errors import LLMError


def _config(**over) -> ModelConfig:
    base = dict(
        name="t",
        protocol="openai-completion",
        base_url="https://api.test",
        model="m",
        key_env="K",
        max_transport_retries=1,
    )
    base.update(over)
    return ModelConfig(**base)


def _client(handler, **over) -> OpenAICompletionClient:
    transport = httpx.MockTransport(handler)
    return OpenAICompletionClient(
        _config(**over), "sk-test", http_client=httpx.Client(transport=transport)
    )


def _ok_payload(usage: dict | None = None) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": "hello"}}],
        "usage": usage
        or {
            "prompt_tokens": 3,
            "completion_tokens": 5,
            "completion_tokens_details": {"reasoning_tokens": 4},
        },
    }


def test_payload_omits_absent_sampling_keys():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_ok_payload())

    client = _client(handler)
    out = client.complete([Message("user", "hi")])
    assert "temperature" not in seen
    assert "reasoning_effort" not in seen
    assert seen["messages"] == [{"role": "user", "content": "hi"}]
    assert out.text == "hello"
    assert out.usage is not None
    assert out.usage.input_tokens == 3
    assert out.usage.output_tokens == 5
    assert out.usage.reasoning_tokens == 4  # 思考 token 单列


def test_payload_sends_explicit_sampling_keys():
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        assert body["temperature"] == 0.2
        assert body["reasoning_effort"] == "low"
        return httpx.Response(200, json=_ok_payload())

    _client(handler, temperature=0.2, reasoning_effort="low").complete(
        [Message("user", "hi")]
    )


def test_usage_missing_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    out = _client(handler).complete([Message("user", "hi")])
    assert out.usage is None  # 端点不返回 => None，不做本地估算


def test_auth_error_not_retried():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(LLMError) as ei:
        _client(handler).complete([Message("user", "hi")])
    assert ei.value.kind == "auth"
    assert calls == 1  # 不重试


def test_rate_limit_retried_then_ok(monkeypatch):
    monkeypatch.setattr("llm.adapters.openai_completion._backoff", lambda *a, **k: None)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json=_ok_payload())

    out = _client(handler).complete([Message("user", "hi")])
    assert out.text == "hello"
    assert calls == 2


def test_bad_json_is_bad_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    with pytest.raises(LLMError) as ei:
        _client(handler).complete([Message("user", "hi")])
    assert ei.value.kind == "bad_response"


def test_unimplemented_protocol_rejected():
    from llm import ConfigError, build_client
    import os

    os.environ["K2"] = "sk-x"
    cfg = ModelConfig(
        name="t", protocol="anthropic", base_url="https://x", model="m", key_env="K2"
    )
    with pytest.raises(ConfigError, match="尚未实现"):
        build_client(cfg)
