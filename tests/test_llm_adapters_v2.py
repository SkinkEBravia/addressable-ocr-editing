"""openai-response / anthropic 适配器的 golden 测试（录制响应回放，不打真实端点）。

对应 Docs/Design/08-llm.md「协议适配器」「验收」：
三适配器对同一 (messages, ModelConfig) 产出各自正确线格式。
"""

from __future__ import annotations

import json

import httpx
import pytest

from llm import Message, ModelConfig
from llm.adapters.anthropic import AnthropicClient
from llm.adapters.openai_response import OpenAIResponseClient
from llm.errors import ConfigError, LLMError

MESSAGES = [
    Message("system", "SYS"),
    Message("user", "hi"),
]


def _config(protocol: str, **over) -> ModelConfig:
    base = dict(
        name="t",
        protocol=protocol,
        base_url="https://api.test",
        model="m",
        key_env="K",
        max_transport_retries=1,
        output_length=1024,
    )
    base.update(over)
    return ModelConfig(**base)


def _client(cls, protocol, handler, **over):
    transport = httpx.MockTransport(handler)
    return cls(
        _config(protocol, **over), "sk-test", http_client=httpx.Client(transport=transport)
    )


# ---------------------------------------------------------------------------
# openai-response
# ---------------------------------------------------------------------------

_RESPONSE_OK = {
    "output": [
        {"type": "reasoning", "summary": []},
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "hello"}],
        },
    ],
    "usage": {
        "input_tokens": 3,
        "output_tokens": 5,
        "output_tokens_details": {"reasoning_tokens": 4},
    },
}


def test_response_wire_format():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/responses"
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_RESPONSE_OK)

    out = _client(OpenAIResponseClient, "openai-response", handler).complete(MESSAGES)
    assert seen["instructions"] == "SYS"  # system 顶层化
    assert seen["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "hi"}]}
    ]
    assert "temperature" not in seen and "reasoning" not in seen  # 缺席 = 不下发
    assert out.text == "hello"
    assert out.usage is not None
    assert (out.usage.input_tokens, out.usage.output_tokens) == (3, 5)
    assert out.usage.reasoning_tokens == 4


def test_response_explicit_sampling_keys():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["temperature"] == 0.2
        assert body["reasoning"] == {"effort": "low"}
        return httpx.Response(200, json=_RESPONSE_OK)

    _client(
        OpenAIResponseClient, "openai-response", handler,
        temperature=0.2, reasoning_effort="low",
    ).complete(MESSAGES)


def test_response_history_roles():
    """多轮历史：assistant 内容部件用 output_text。"""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["input"][-1] == {
            "role": "assistant",
            "content": [{"type": "output_text", "text": "prev"}],
        }
        return httpx.Response(200, json=_RESPONSE_OK)

    _client(OpenAIResponseClient, "openai-response", handler).complete(
        MESSAGES + [Message("assistant", "prev")]
    )


def test_response_usage_missing_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output": _RESPONSE_OK["output"]})

    out = _client(OpenAIResponseClient, "openai-response", handler).complete(MESSAGES)
    assert out.usage is None


_RESPONSE_SSE = (
    'data: {"type":"response.reasoning_text.delta","delta":"想"}\n\n'
    'data: {"type":"response.output_text.delta","delta":"hel"}\n\n'
    'data: {"type":"response.output_text.delta","delta":"lo"}\n\n'
    'data: {"type":"response.completed","response":{"usage":{"input_tokens":3,'
    '"output_tokens":5,"output_tokens_details":{"reasoning_tokens":2}}}}\n\n'
)


def test_response_streaming():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True
        return httpx.Response(
            200,
            content=_RESPONSE_SSE.encode(),
            headers={"Content-Type": "text/event-stream"},
        )

    deltas: list[str] = []
    out = _client(OpenAIResponseClient, "openai-response", handler).complete(
        MESSAGES, on_delta=deltas.append
    )
    assert deltas == ["想", "hel", "lo"]
    assert out.text == "hello"  # 思考不进正文
    assert out.usage is not None and out.usage.reasoning_tokens == 2


# ---------------------------------------------------------------------------
# anthropic
# ---------------------------------------------------------------------------

_ANTHROPIC_OK = {
    "content": [{"type": "text", "text": "hello"}],
    "usage": {"input_tokens": 3, "output_tokens": 5},
}


def test_anthropic_wire_format():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert request.headers["x-api-key"] == "sk-test"
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_ANTHROPIC_OK)

    out = _client(AnthropicClient, "anthropic", handler).complete(MESSAGES)
    assert seen["system"] == "SYS"  # system 顶层化
    assert seen["messages"] == [{"role": "user", "content": "hi"}]
    assert seen["max_tokens"] == 1024  # output_length 强制下发
    assert "temperature" not in seen
    assert out.text == "hello"
    assert out.usage is not None
    assert (out.usage.input_tokens, out.usage.output_tokens) == (3, 5)
    assert out.usage.reasoning_tokens is None  # Anthropic 不单列思考 token


def test_anthropic_usage_sums_cache_fields():
    """缓存命中时 input_tokens 只报未命中部分；适配器求和缓存字段对齐口径。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "x"}],
                "usage": {
                    "input_tokens": 95,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 896,
                    "output_tokens": 102,
                },
            },
        )

    out = _client(AnthropicClient, "anthropic", handler).complete(MESSAGES)
    assert out.usage is not None
    assert out.usage.input_tokens == 991  # 95 + 896，与 OpenAI 系 prompt_tokens 口径对齐
    assert out.usage.output_tokens == 102


def test_anthropic_requires_output_length():
    with pytest.raises(ConfigError, match="output_length"):
        _client(AnthropicClient, "anthropic", lambda r: None, output_length=None).complete(
            MESSAGES
        )


def test_anthropic_rejects_reasoning_effort():
    with pytest.raises(ConfigError, match="reasoning_effort"):
        _client(
            AnthropicClient, "anthropic", lambda r: None, reasoning_effort="low"
        ).complete(MESSAGES)


_ANTHROPIC_SSE = (
    'data: {"type":"message_start","message":{"usage":{"input_tokens":3,'
    '"output_tokens":1}}}\n\n'
    'data: {"type":"content_block_delta","index":0,"delta":'
    '{"type":"thinking_delta","thinking":"想"}}\n\n'
    'data: {"type":"content_block_delta","index":1,"delta":'
    '{"type":"text_delta","text":"hel"}}\n\n'
    'data: {"type":"content_block_delta","index":1,"delta":'
    '{"type":"text_delta","text":"lo"}}\n\n'
    'data: {"type":"message_delta","usage":{"output_tokens":5}}\n\n'
)


def test_anthropic_streaming():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True
        return httpx.Response(
            200,
            content=_ANTHROPIC_SSE.encode(),
            headers={"Content-Type": "text/event-stream"},
        )

    deltas: list[str] = []
    out = _client(AnthropicClient, "anthropic", handler).complete(
        MESSAGES, on_delta=deltas.append
    )
    assert deltas == ["想", "hel", "lo"]
    assert out.text == "hello"
    assert out.usage is not None
    assert (out.usage.input_tokens, out.usage.output_tokens) == (3, 5)


def test_anthropic_auth_error_not_retried():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": {"type": "authentication_error"}})

    with pytest.raises(LLMError) as ei:
        _client(AnthropicClient, "anthropic", handler).complete(MESSAGES)
    assert ei.value.kind == "auth"
    assert calls == 1


def test_build_client_dispatch():
    """build_client 按 protocol 分派三适配器；未知协议 ConfigError。"""
    import os

    from llm import build_client
    from llm.adapters.openai_completion import OpenAICompletionClient

    os.environ["K3"] = "sk-x"
    for protocol, cls in (
        ("openai-completion", OpenAICompletionClient),
        ("openai-response", OpenAIResponseClient),
        ("anthropic", AnthropicClient),
    ):
        client = build_client(_config(protocol, key_env="K3"))
        assert isinstance(client, cls)
    with pytest.raises(ConfigError, match="未知 protocol"):
        build_client(_config("openai-chat", key_env="K3"))
