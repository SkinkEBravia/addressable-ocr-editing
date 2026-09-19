"""llm 适配器：golden 线格式与错误分类（Docs/Design/08-llm.md「验收」）。

全部经 httpx.MockTransport 离线运行；重试的 backoff 打桩掉。
"""

from __future__ import annotations

import json
import logging
import time

import httpx
import pytest

from llm import ConfigError, LLMError, Message, model_config_from_dict
from llm.adapters import _transport
from llm.adapters.anthropic import AnthropicClient
from llm.adapters.openai_completion import OpenAICompletionClient
from llm.adapters.openai_response import OpenAIResponseClient
from llm.types import Completion

KEY = "sk-test-secret"

MSGS = [Message("system", "sys"), Message("user", "hello")]


def make_config(protocol: str, **extra):
    d = {
        "protocol": protocol,
        "base_url": "https://api.test",
        "model": "m1",
        "key_env": "TEST_KEY",
        "max_transport_retries": 1,
    }
    d.update(extra)
    return model_config_from_dict("test", d)


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(_transport, "backoff", lambda *a, **k: None)


def sse(*objs: dict) -> bytes:
    body = "".join(f"data: {json.dumps(o)}\n\n" for o in objs)
    return (body + "data: [DONE]\n\n").encode()


# ---------------------------------------------------------------- openai-response


def _resp_payload(text: str = "world") -> dict:
    return {
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": text}]}
        ],
        "usage": {
            "input_tokens": 3,
            "output_tokens": 2,
            "output_tokens_details": {"reasoning_tokens": 1},
        },
    }


def test_response_wire_format():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json=_resp_payload())

    client = OpenAIResponseClient(
        make_config("openai-response", reasoning_effort="low"),
        KEY,
        http_client=mock_client(handler),
    )
    comp = client.complete(MSGS)
    assert seen["url"] == "https://api.test/responses"
    assert seen["body"]["instructions"] == "sys"
    assert seen["body"]["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "hello"}]}
    ]
    assert seen["body"]["reasoning"] == {"effort": "low"}
    assert comp.text == "world"
    assert comp.usage is not None
    assert (comp.usage.input_tokens, comp.usage.output_tokens) == (3, 2)
    assert comp.usage.reasoning_tokens == 1


def test_response_sends_max_output_tokens_when_configured():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json=_resp_payload())

    # 显式 output_length ⇒ 下发 max_output_tokens
    client = OpenAIResponseClient(
        make_config("openai-response", output_length=393216),
        KEY,
        http_client=mock_client(handler),
    )
    client.complete(MSGS)
    assert seen["body"]["max_output_tokens"] == 393216

    # 缺席 ⇒ 不下发
    client2 = OpenAIResponseClient(
        make_config("openai-response"), KEY, http_client=mock_client(handler)
    )
    client2.complete(MSGS)
    assert "max_output_tokens" not in seen["body"]


def test_response_rejected_4xx_no_retry():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, text="bad request: input too large")

    client = OpenAIResponseClient(
        make_config("openai-response"), KEY, http_client=mock_client(handler)
    )
    with pytest.raises(LLMError) as ei:
        client.complete(MSGS)
    f = ei.value.failure
    assert f.kind == "rejected" and f.http_status == 400 and f.attempts == 1
    assert "input too large" in f.detail["body_excerpt"]
    assert calls == 1  # 不重试
    assert KEY not in str(ei.value) and KEY not in json.dumps(f.detail)


def test_response_auth_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    client = OpenAIResponseClient(
        make_config("openai-response"), KEY, http_client=mock_client(handler)
    )
    with pytest.raises(LLMError) as ei:
        client.complete(MSGS)
    assert ei.value.failure.kind == "auth"
    assert ei.value.failure.attempts == 1


def test_response_rate_limit_retried_then_failed():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "0"}, text="slow down")

    client = OpenAIResponseClient(
        make_config("openai-response"), KEY, http_client=mock_client(handler)
    )
    with pytest.raises(LLMError) as ei:
        client.complete(MSGS)
    f = ei.value.failure
    assert f.kind == "rate_limit" and f.attempts == 2  # max_transport_retries=1
    assert f.elapsed_s is not None
    assert calls == 2


def test_response_garbage_body_protocol_mismatch():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway error</html>")

    client = OpenAIResponseClient(
        make_config("openai-response"), KEY, http_client=mock_client(handler)
    )
    with pytest.raises(LLMError) as ei:
        client.complete(MSGS)
    assert ei.value.failure.kind == "protocol_mismatch"


def test_response_no_output_text_incomplete():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "completed", "output": []})

    client = OpenAIResponseClient(
        make_config("openai-response"), KEY, http_client=mock_client(handler)
    )
    with pytest.raises(LLMError) as ei:
        client.complete(MSGS)
    assert ei.value.failure.kind == "incomplete"


def test_response_stream_happy_path():
    events = [
        {"type": "response.output_text.delta", "delta": "wor"},
        {"type": "response.reasoning_text.delta", "delta": "thinking…"},
        {"type": "response.output_text.delta", "delta": "ld"},
        {"type": "response.completed", "response": _resp_payload("world")},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse(*events))

    client = OpenAIResponseClient(
        make_config("openai-response"), KEY, http_client=mock_client(handler)
    )
    deltas: list[str] = []
    comp = client.complete(MSGS, on_delta=deltas.append)
    assert comp.text == "world"
    assert deltas == ["wor", "thinking…", "ld"]  # 思考增量也可观测
    assert comp.usage is not None and comp.usage.output_tokens == 2


def test_response_stream_zero_data_events():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>blocked</html>")

    client = OpenAIResponseClient(
        make_config("openai-response"), KEY, http_client=mock_client(handler)
    )
    with pytest.raises(LLMError) as ei:
        client.complete(MSGS, on_delta=lambda s: None)
    assert ei.value.failure.kind == "protocol_mismatch"


def test_response_stream_incomplete_no_text():
    events = [
        {"type": "response.reasoning_text.delta", "delta": "thinking…"},
        {
            "type": "response.incomplete",
            "response": {
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output": [],
            },
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse(*events))

    client = OpenAIResponseClient(
        make_config("openai-response"), KEY, http_client=mock_client(handler)
    )
    with pytest.raises(LLMError) as ei:
        client.complete(MSGS, on_delta=lambda s: None)
    f = ei.value.failure
    assert f.kind == "incomplete"
    assert f.detail["final_event"] == "response.incomplete"
    assert f.detail["incomplete_details"] == {"reason": "max_output_tokens"}


def test_response_stream_failed_rate_limit_is_retried():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                content=sse(
                    {
                        "type": "response.failed",
                        "response": {
                            "status": "failed",
                            "error": {
                                "code": "rate_limit_exceeded",
                                "message": "slow down",
                            },
                        },
                    }
                ),
            )
        return httpx.Response(200, content=sse(
            {"type": "response.output_text.delta", "delta": "ok"},
            {"type": "response.completed", "response": _resp_payload("ok")},
        ))

    client = OpenAIResponseClient(
        make_config("openai-response"), KEY, http_client=mock_client(handler)
    )
    comp = client.complete(MSGS, on_delta=lambda s: None)
    assert comp.text == "ok" and calls == 2  # 重试通道生效


def test_response_stream_failed_burst_is_retried():
    """火山的 RequestBurstTooFast（突发流量保护）= 限流，退避后重试。"""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                content=sse(
                    {
                        "type": "response.failed",
                        "response": {
                            "status": "failed",
                            "error": {
                                "code": "RequestBurstTooFast",
                                "message": "System protection triggered by request burst.",
                            },
                        },
                    }
                ),
            )
        return httpx.Response(200, content=sse(
            {"type": "response.output_text.delta", "delta": "ok"},
            {"type": "response.completed", "response": _resp_payload("ok")},
        ))

    client = OpenAIResponseClient(
        make_config("openai-response"), KEY, http_client=mock_client(handler)
    )
    comp = client.complete(MSGS, on_delta=lambda s: None)
    assert comp.text == "ok" and calls == 2


# ---------------------------------------------------------------- 流式停滞看门狗


class _StubStreamResponse:
    """iter_lines + close 的鸭子类型桩；hang=True 时 lines 发完后挂住（模拟无终结事件）。"""

    def __init__(self, lines: list[str], gap: float = 0.0, hang: bool = True):
        self._lines = lines
        self._gap = gap
        self._hang = hang
        self.closed = False

    def iter_lines(self):
        for line in self._lines:
            if self.closed:
                return
            if self._gap:
                time.sleep(self._gap)
            yield line
        while self._hang and not self.closed:  # 挂住：连接开着但不再来数据
            time.sleep(0.01)

    def close(self):
        self.closed = True


def test_sse_stall_aborts_despite_heartbeats():
    """心跳注释行不重置停滞计时：只来心跳也照掐。"""
    resp = _StubStreamResponse([": ping"] * 1000, gap=0.01)
    t0 = time.monotonic()
    with pytest.raises(_transport.Retryable) as ei:
        list(_transport.iter_sse_data_lines(resp, stall_timeout=0.2))
    assert ei.value.kind == "timeout"
    assert resp.closed  # 掐流让 pump 线程退出
    assert time.monotonic() - t0 < 5


def test_sse_data_flow_no_stall():
    """data 行持续到达（间隔 < 阈值）不触发看门狗，全部照常产出。"""
    lines = [f"data: {json.dumps({'n': i})}" for i in range(5)]
    resp = _StubStreamResponse(lines, gap=0.05, hang=False)
    got = list(_transport.iter_sse_data_lines(resp, stall_timeout=0.5))
    assert len(got) == 5


def test_retry_logged(caplog):
    """重试通道的每次退避都落日志（llm.transport），含 kind 与 attempt。"""
    def fn(a: int):
        if a == 1:
            raise _transport.Retryable("boom", kind="rate_limit")
        return Completion(text="ok", usage=None)

    with caplog.at_level(logging.WARNING, logger="llm.transport"):
        comp = _transport.call_with_retries(make_config("openai-response"), fn)
    assert comp.text == "ok"
    assert any(
        "rate_limit" in r.message and "attempt=1" in r.message
        for r in caplog.records
    )


def test_delta_stall_watchdog():
    """增量级看门狗：假时钟下 feed 重置计时，超阈值抛 Retryable(timeout)。"""
    clock = {"t": 1000.0}
    dog = _transport.DeltaStallWatchdog(300.0, now=lambda: clock["t"])
    clock["t"] += 299.0
    dog.check()  # 299s 未到阈值
    dog.feed()   # 有增量，重置
    clock["t"] += 299.0
    dog.check()
    clock["t"] += 2.0  # 距上次 feed 301s
    with pytest.raises(_transport.Retryable) as ei:
        dog.check(context="last_event=response.in_progress")
    assert ei.value.kind == "timeout"
    assert "in_progress" in str(ei.value)


# ---------------------------------------------------------------- openai-completion


def test_completion_wire_format_and_empty_content():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "hi"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1},
            },
        )

    client = OpenAICompletionClient(
        make_config("openai-completion", temperature=0.2),
        KEY,
        http_client=mock_client(handler),
    )
    comp = client.complete(MSGS)
    assert seen["body"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    assert seen["body"]["temperature"] == 0.2
    assert comp.text == "hi" and comp.usage is not None

    def empty_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": ""}}]}
        )

    client2 = OpenAICompletionClient(
        make_config("openai-completion"), KEY, http_client=mock_client(empty_handler)
    )
    with pytest.raises(LLMError) as ei:
        client2.complete(MSGS)
    assert ei.value.failure.kind == "incomplete"  # 空文本永不静默接受


# ---------------------------------------------------------------- anthropic


def test_anthropic_requires_output_length():
    client = AnthropicClient(
        make_config("anthropic"), KEY, http_client=mock_client(lambda r: httpx.Response(200))
    )
    with pytest.raises(ConfigError):
        client.complete(MSGS)


def test_anthropic_rejects_reasoning_effort():
    client = AnthropicClient(
        make_config("anthropic", output_length=100, reasoning_effort="low"),
        KEY,
        http_client=mock_client(lambda r: httpx.Response(200)),
    )
    with pytest.raises(ConfigError):
        client.complete(MSGS)


def test_anthropic_wire_format():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read())
        seen["version"] = request.headers.get("anthropic-version")
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "hi"}],
                "usage": {"input_tokens": 4, "output_tokens": 1},
            },
        )

    client = AnthropicClient(
        make_config("anthropic", output_length=100), KEY, http_client=mock_client(handler)
    )
    comp = client.complete(MSGS)
    assert seen["body"]["system"] == "sys"
    assert seen["body"]["max_tokens"] == 100
    assert seen["body"]["messages"] == [{"role": "user", "content": "hello"}]
    assert comp.text == "hi"


# ---------------------------------------------------------------- extra_body


def _completion_payload(text: str = "world") -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }


def test_response_extra_body_passthrough():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json=_resp_payload())

    client = OpenAIResponseClient(
        make_config(
            "openai-response",
            extra_body={"provider": {"only": ["modal/fp8"]}},
        ),
        KEY,
        http_client=mock_client(handler),
    )
    client.complete(MSGS)
    assert seen["body"]["provider"] == {"only": ["modal/fp8"]}
    # 核心字段不被 extra_body 覆盖
    assert seen["body"]["model"] == "m1"


def test_completion_extra_body_passthrough():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json=_completion_payload())

    client = OpenAICompletionClient(
        make_config(
            "openai-completion",
            extra_body={"provider": {"only": ["modal/fp8"]}},
        ),
        KEY,
        http_client=mock_client(handler),
    )
    client.complete(MSGS)
    assert seen["body"]["provider"] == {"only": ["modal/fp8"]}
    assert seen["body"]["model"] == "m1"


def test_anthropic_rejects_extra_body():
    client = AnthropicClient(
        make_config(
            "anthropic",
            output_length=100,
            extra_body={"provider": {"only": ["modal/fp8"]}},
        ),
        KEY,
        http_client=mock_client(lambda r: httpx.Response(200)),
    )
    with pytest.raises(ConfigError):
        client.complete(MSGS)
