"""Public client contract against actual LiteLLM, with all HTTP requests mocked."""

from __future__ import annotations

import json

import httpx
import pytest

from llm import ConfigError, LLMError, Message, build_client, model_config_from_dict
from llm.litellm_client import LiteLLMClient


MESSAGES = [Message("system", "system text"), Message("user", "hello")]


def config(protocol="openai-completion", **options):
    return model_config_from_dict("test", {"protocol": protocol, "model": "m1", "base_url": "https://api.test",
                                           "key_env": "TEST_LLM_KEY", "max_transport_retries": 0, **options})


def response_body(protocol, *, usage=True, text="ok"):
    if protocol == "openai-completion":
        result = {"id": "r", "object": "chat.completion", "model": "m1", "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}
        counts = {"prompt_tokens": 4, "completion_tokens": 2, "completion_tokens_details": {"reasoning_tokens": 1}}
    elif protocol == "anthropic":
        result = {"id": "r", "type": "message", "model": "m1", "role": "assistant", "content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}
        counts = {"input_tokens": 1, "cache_read_input_tokens": 2, "cache_creation_input_tokens": 1, "output_tokens": 2}
    else:
        result = {"id": "r", "object": "response", "created_at": 1, "model": "m1", "status": "completed", "output": [{"id": "m", "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": text, "annotations": []}]}]}
        counts = {"input_tokens": 4, "output_tokens": 2, "output_tokens_details": {"reasoning_tokens": 1}}
    if usage:
        result["usage"] = counts
    return result


def install_http(monkeypatch, handler):
    requests = []
    def send(client, request, **kwargs):
        assert request.url.host == "api.test", "offline test attempted external HTTP"
        requests.append(request)
        response = handler(request)
        response.request = request
        return response
    monkeypatch.setattr(httpx.Client, "send", send)
    return requests


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr("llm.litellm_client._retry_wait", lambda state: 0)


@pytest.mark.parametrize("protocol,path", [("openai-completion", "/chat/completions"), ("openai-response", "/responses"), ("anthropic", "/v1/messages")])
def test_wire_format_and_usage(monkeypatch, protocol, path):
    monkeypatch.setenv("TEST_LLM_KEY", "dummy-secret")
    requests = install_http(monkeypatch, lambda req: httpx.Response(200, json=response_body(protocol)))
    client = build_client(config(protocol, output_length=16))
    result = client.complete(MESSAGES)
    assert result.text == "ok"
    assert result.usage.input_tokens == 4 and result.usage.output_tokens == 2
    assert result.elapsed_s >= 0
    assert len(requests) == 1 and requests[0].url.path == path
    body = json.loads(requests[0].content)
    assert body["model"] == "m1"
    assert body["max_output_tokens" if protocol == "openai-response" else "max_tokens"] == 16
    assert "temperature" not in body
    if protocol == "openai-response":
        assert body["instructions"] == "system text"
    elif protocol == "anthropic":
        assert body["system"] == [{"type": "text", "text": "system text"}]
    else:
        assert body["messages"] == [{"role": m.role, "content": m.content} for m in MESSAGES]


@pytest.mark.parametrize("protocol", ["openai-completion", "openai-response", "anthropic"])
def test_missing_server_usage_is_not_sdk_zero_or_estimate(monkeypatch, protocol):
    install_http(monkeypatch, lambda req: httpx.Response(200, json=response_body(protocol, usage=False)))
    result = LiteLLMClient(config(protocol, output_length=16), "dummy").complete(MESSAGES)
    assert result.usage is None


@pytest.mark.parametrize("protocol", ["openai-completion", "openai-response", "anthropic"])
def test_empty_answer_never_returns_success(monkeypatch, protocol):
    install_http(monkeypatch, lambda req: httpx.Response(200, json=response_body(protocol, text="")))
    with pytest.raises(LLMError):
        LiteLLMClient(config(protocol, output_length=16), "dummy").complete(MESSAGES)


def test_failed_response_with_partial_text_uses_retry_channel(monkeypatch):
    body = response_body("openai-response", text="partial")
    body.update(status="failed", error={"code": "rate_limit_exceeded", "message": "slow down"})
    requests = install_http(monkeypatch, lambda req: httpx.Response(200, json=body))
    with pytest.raises(LLMError) as error:
        LiteLLMClient(config("openai-response", max_transport_retries=1), "dummy").complete(MESSAGES)
    assert error.value.kind == "rate_limit"
    assert error.value.attempts == 2 and len(requests) == 2


@pytest.mark.parametrize("status,kind,attempts", [(400, "rejected", 1), (401, "auth", 1), (408, "timeout", 2), (409, "rejected", 1), (429, "rate_limit", 2), (503, "server", 2)])
def test_http_failure_and_single_retry_budget(monkeypatch, status, kind, attempts):
    requests = install_http(monkeypatch, lambda req: httpx.Response(status, json={"error": {"message": "dummy-secret"}}))
    client = LiteLLMClient(config(max_transport_retries=1), "dummy-secret")
    with pytest.raises(LLMError) as error:
        client.complete(MESSAGES)
    assert error.value.kind == kind
    assert error.value.attempts == attempts and len(requests) == attempts
    assert "dummy-secret" not in json.dumps(error.value.failure.to_dict())


def test_extra_body_cannot_override_core_parameters(monkeypatch):
    requests = install_http(monkeypatch, lambda req: httpx.Response(200, json=response_body("openai-completion")))
    LiteLLMClient(config(extra_body={"model": "other", "temperature": 0.9, "provider": {"only": ["test"]}}), "dummy").complete(MESSAGES)
    body = json.loads(requests[0].content)
    assert body["model"] == "m1" and "temperature" not in body
    assert body["provider"] == {"only": ["test"]}


@pytest.mark.parametrize("options", [{}, {"output_length": 8, "reasoning_effort": "low"}, {"output_length": 8, "extra_body": {}}])
def test_anthropic_project_constraints_remain_explicit(options):
    with pytest.raises(ConfigError):
        LiteLLMClient(config("anthropic", **options), "dummy")


def stream_bytes(protocol, *, usage=True, finish=True):
    if protocol == "openai-response":
        events = [{"type": "response.output_text.delta", "delta": "ok", "item_id": "m", "output_index": 0, "content_index": 0, "sequence_number": 1}]
        if finish:
            events.append({"type": "response.completed", "sequence_number": 2, "response": response_body(protocol, usage=usage)})
    elif protocol == "anthropic":
        start = response_body(protocol, text="")
        start["content"] = []
        start["usage"]["output_tokens"] = 0
        if not usage:
            start["usage"] = None
        events = [{"type": "message_start", "message": start},
                  {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                  {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}},
                  {"type": "content_block_stop", "index": 0}]
        if finish:
            events += [{"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 2}}, {"type": "message_stop"}]
            if not usage:
                events[-2]["usage"] = None
    else:
        events = [{"id": "r", "object": "chat.completion.chunk", "created": 1, "model": "m1", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "ok"}, "finish_reason": None}]}]
        if finish:
            events.append({"id": "r", "object": "chat.completion.chunk", "created": 1, "model": "m1", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        if usage:
            events.append({"id": "r", "object": "chat.completion.chunk", "created": 1, "model": "m1", "choices": [], "usage": response_body(protocol)["usage"]})
    body = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
    return (body + ("data: [DONE]\n\n" if protocol == "openai-completion" and finish else "")).encode()


@pytest.mark.parametrize("protocol", ["openai-completion", "openai-response", "anthropic"])
def test_streaming_text_and_provider_usage(monkeypatch, protocol):
    install_http(monkeypatch, lambda req: httpx.Response(200, content=stream_bytes(protocol), headers={"content-type": "text/event-stream"}))
    observed = []
    result = LiteLLMClient(config(protocol, output_length=16), "dummy").complete(MESSAGES, on_delta=observed.append)
    assert result.text == "ok" and "".join(observed) == "ok"
    assert result.usage.input_tokens == 4 and result.usage.output_tokens == 2
    assert result.raw["format"] == ("provider-response" if protocol == "openai-response" else "litellm-normalized")


@pytest.mark.parametrize("protocol", ["openai-completion", "openai-response", "anthropic"])
def test_stream_missing_server_usage_stays_missing(monkeypatch, protocol):
    install_http(monkeypatch, lambda req: httpx.Response(200, content=stream_bytes(protocol, usage=False), headers={"content-type": "text/event-stream"}))
    result = LiteLLMClient(config(protocol, output_length=16), "dummy").complete(MESSAGES, on_delta=lambda text: None)
    assert result.usage is None


@pytest.mark.parametrize("protocol", ["openai-completion", "openai-response", "anthropic"])
def test_stream_without_provider_finish_is_not_success(monkeypatch, protocol):
    install_http(monkeypatch, lambda req: httpx.Response(200, content=stream_bytes(protocol, finish=False), headers={"content-type": "text/event-stream"}))
    with pytest.raises(LLMError) as error:
        LiteLLMClient(config(protocol, output_length=16), "dummy").complete(MESSAGES, on_delta=lambda text: None)
    # Responses SDK reports an EOF without its required terminal event as a
    # transport interruption; either category must remain an explicit failure.
    assert error.value.kind in ("incomplete", "timeout")


def test_partial_stream_read_error_is_retried_with_one_budget(monkeypatch):
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield stream_bytes("openai-completion", usage=False, finish=False)
            raise httpx.ReadError("interrupted")
    requests = install_http(monkeypatch, lambda req: httpx.Response(200, stream=Broken(), headers={"content-type": "text/event-stream"}))
    with pytest.raises(LLMError) as error:
        LiteLLMClient(config(max_transport_retries=1), "dummy").complete(MESSAGES, on_delta=lambda text: None)
    assert error.value.kind == "timeout"
    assert error.value.attempts == 2 and len(requests) == 2


def test_sdk_iterator_stall_closes_stream(monkeypatch):
    import threading
    from llm import litellm_client
    closed = threading.Event()
    class Stalled:
        def __iter__(self):
            closed.wait(2)
            return iter(())
        def close(self):
            closed.set()
    monkeypatch.setattr(litellm_client, "STREAM_STALL_SECONDS", 0.03)
    with pytest.raises(LLMError) as error:
        list(LiteLLMClient._events(Stalled(), lambda: litellm_client.time.monotonic() - 0.01, 1))
    assert error.value.kind == "timeout" and closed.is_set()
