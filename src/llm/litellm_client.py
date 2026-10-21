"""LiteLLM implementation of the project's message/result interface.

Protocol I/O belongs to LiteLLM. This module keeps configuration, server usage,
failure records and the single whole-call retry budget local to the project.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import httpx
from tenacity import Retrying, retry_if_exception, stop_after_attempt

from llm.config import ModelConfig, PROTOCOLS
from llm.errors import ConfigError, Failure, LLMError
from llm.types import Completion, Message, Usage

logger = logging.getLogger("llm")
STREAM_STALL_SECONDS = 300.0


def _dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", warnings=False)
    return {}


def _usage(value: Any, *, anthropic: bool = False) -> Usage | None:
    data = _dict(value)
    input_name = "input_tokens" if "input_tokens" in data else "prompt_tokens"
    output_name = "output_tokens" if "output_tokens" in data else "completion_tokens"
    incoming, outgoing = data.get(input_name), data.get(output_name)
    if type(incoming) is not int or type(outgoing) is not int:
        return None
    if anthropic:
        incoming += sum(data.get(k, 0) for k in ("cache_read_input_tokens", "cache_creation_input_tokens") if type(data.get(k, 0)) is int)
    details = _dict(data.get("output_tokens_details") or data.get("completion_tokens_details"))
    reasoning = details.get("reasoning_tokens")
    return Usage(incoming, outgoing, reasoning if type(reasoning) is int and not anthropic else None)


def _validate(config: ModelConfig) -> None:
    if config.protocol not in PROTOCOLS:
        raise ConfigError(f"unknown protocol: {config.protocol!r}")
    if config.reasoning_effort not in (None, "low", "medium", "high"):
        raise ConfigError("reasoning_effort must be low, medium or high")
    if config.max_transport_retries < 0 or config.timeout <= 0:
        raise ConfigError("retry count must be nonnegative and timeout must be positive")
    if config.output_length is not None and config.output_length <= 0:
        raise ConfigError("output_length must be positive")
    if config.protocol == "anthropic":
        if config.output_length is None:
            raise ConfigError("anthropic requires output_length")
        if config.reasoning_effort is not None or config.extra_body is not None:
            raise ConfigError("anthropic does not support reasoning_effort or extra_body in this interface")


def _retryable(exc: BaseException) -> bool:
    return isinstance(exc, LLMError) and exc.kind in ("timeout", "rate_limit", "server")


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "<redacted>")
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value


def _exception_chain(error):
    pending, seen = [error], set()
    while pending:
        item = pending.pop()
        if item is None or id(item) in seen:
            continue
        seen.add(id(item))
        yield item
        pending.extend(getattr(item, name, None) for name in ("original_exception", "__cause__", "__context__"))


def _retry_wait(state) -> float:
    delay = min(60.0, 2.0 ** (state.attempt_number - 1))
    error = state.outcome.exception()
    try:
        delay = max(delay, float(error.failure.detail.get("retry_after", 0)))
    except (ValueError, TypeError):
        pass
    logger.warning("LLM retry attempt=%d kind=%s delay=%.1fs", state.attempt_number, error.kind, delay)
    return delay


class LiteLLMClient:
    """Stateless client; callers own history and receive only project types."""

    def __init__(self, config: ModelConfig, api_key: str) -> None:
        _validate(config)
        self._config = config
        self._api_key = api_key

    def complete(self, messages: list[Message], *, on_delta: Callable[[str], None] | None = None) -> Completion:
        # Use the installed version's bundled metadata; importing the client does
        # not need an unrelated request for the latest model-price table.
        os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
        import litellm

        litellm.suppress_debug_info = True
        attempts = 0
        started = time.monotonic()

        def once() -> Completion:
            nonlocal attempts
            attempts += 1
            trace: dict[str, Any] = {}
            def capture(data):
                if data.get("log_event_type") == "post_api_call":
                    raw = data.get("original_response")
                    try:
                        raw = json.loads(raw) if isinstance(raw, str) else raw
                    except (ValueError, TypeError):
                        return
                    if isinstance(raw, dict):
                        trace.update(raw)
            try:
                return self._once(litellm, messages, on_delta, capture, trace, attempts)
            except LLMError:
                raise
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if any(isinstance(cause, (httpx.TransportError, litellm.Timeout)) for cause in _exception_chain(exc)):
                    kind = "timeout"
                elif isinstance(exc, litellm.APIConnectionError):
                    kind = "protocol_mismatch" if trace else "timeout"
                elif status == 429:
                    kind = "rate_limit"
                elif isinstance(status, int) and status >= 500:
                    kind = "server"
                elif status in (401, 403):
                    kind = "auth"
                elif isinstance(status, int) and status >= 400:
                    kind = "rejected"
                else:
                    kind = "protocol_mismatch"
                response = getattr(exc, "response", None)
                retry_after = getattr(response, "headers", {}).get("Retry-After")
                message = str(exc).replace(self._api_key, "<redacted>")[:500]
                raise LLMError(Failure("llm", kind, message, http_status=status, attempts=attempts,
                                       detail={"retry_after": retry_after} if retry_after else {})) from exc

        retryer = Retrying(stop=stop_after_attempt(self._config.max_transport_retries + 1),
                           retry=retry_if_exception(_retryable), wait=_retry_wait, reraise=True)
        try:
            result = retryer(once)
        except LLMError as exc:
            raise LLMError(replace(
                exc.failure, attempts=attempts, elapsed_s=time.monotonic() - started,
                message=_redact(exc.failure.message, self._api_key),
                detail=_redact(exc.failure.detail, self._api_key),
            )) from exc
        return replace(result, elapsed_s=time.monotonic() - started)

    def _once(self, sdk, messages, on_delta, capture, trace, attempts) -> Completion:
        config = self._config
        responses = config.protocol == "openai-response"
        if responses:
            # The selected protocol explicitly supports SSE. Unknown model names
            # must not trigger LiteLLM's catalogue-based fake-stream fallback.
            sdk.register_model({"openai/" + config.model: {"litellm_provider": "openai", "supports_native_streaming": True}})
        params: dict[str, Any] = {
            "model": ("anthropic/" if config.protocol == "anthropic" else "openai/") + config.model,
            "api_base": config.base_url.rstrip("/"), "api_key": self._api_key,
            "num_retries": 0, "max_retries": 0, "drop_params": False,
            "caching": False, "logger_fn": capture,
            "timeout": httpx.Timeout(config.timeout, read=min(config.timeout, STREAM_STALL_SECONDS)) if on_delta else config.timeout,
        }
        if config.temperature is not None:
            params["temperature"] = config.temperature
        if config.output_length is not None:
            params["max_output_tokens" if responses else "max_tokens"] = config.output_length
        if config.reasoning_effort is not None:
            params["reasoning" if responses else "reasoning_effort"] = {"effort": config.reasoning_effort} if responses else config.reasoning_effort
        if config.extra_body:
            protected = {"model", "messages", "input", "instructions", "temperature", "reasoning", "reasoning_effort", "max_tokens", "max_output_tokens", "stream"}
            params["extra_body"] = {k: v for k, v in config.extra_body.items() if k not in protected}
        if responses:
            instructions = "\n\n".join(m.content for m in messages if m.role == "system")
            if instructions:
                params["instructions"] = instructions
            params["input"] = [{"role": m.role, "content": [{"type": "output_text" if m.role == "assistant" else "input_text", "text": m.content}]} for m in messages if m.role != "system"]
            invoke = sdk.responses
        else:
            params["messages"] = [{"role": m.role, "content": m.content} for m in messages]
            invoke = sdk.completion
        if on_delta is not None:
            params["stream"] = True
            if not responses:
                params["stream_options"] = {"include_usage": True}
            if config.protocol == "anthropic":
                # This SDK iterator does not expose its HTTP response for close().
                # Own its transport so abandoning the observed stream also closes
                # the underlying connection, including on watchdog timeout.
                from litellm.llms.custom_httpx.http_handler import HTTPHandler
                with httpx.Client(timeout=params["timeout"]) as transport:
                    params["client"] = HTTPHandler(client=transport)
                    return self._stream(invoke(**params), on_delta, responses, attempts)
            return self._stream(invoke(**params), on_delta, responses, attempts)
        try:
            response = _dict(invoke(**params))
        except sdk.APIConnectionError:
            # LiteLLM 1.106 indexes Anthropic's optional usage unconditionally.
            # Its post-call hook has already captured the valid provider message;
            # preserve the answer and missing usage rather than inventing counts.
            if config.protocol != "anthropic" or isinstance(trace.get("usage"), dict) or trace.get("type") != "message":
                raise
            text = "".join(part.get("text", "") for part in trace.get("content", []) if part.get("type") == "text")
            if not text:
                raise
            response = {"choices": [{"message": {"content": text}}]}
        raw = trace or response
        if responses:
            self._check_response(response, attempts)
            text = "".join(p.get("text", "") for item in response.get("output", []) if item.get("type") == "message" for p in item.get("content", []) if p.get("type") == "output_text")
        else:
            choices = response.get("choices") or []
            text = _dict(choices[0].get("message")).get("content") if choices else None
        if not isinstance(text, str) or not text:
            raise LLMError(Failure("llm", "incomplete", "response has no answer text", attempts=attempts))
        usage = _usage(raw.get("usage"), anthropic=config.protocol == "anthropic")
        return Completion(text, usage, raw)

    @staticmethod
    def _check_response(response, attempts):
        if response.get("status") == "failed":
            code = str(_dict(response.get("error")).get("code", "")).lower()
            kind = "rate_limit" if "rate_limit" in code or "burst" in code else "server" if "server" in code else "incomplete"
            raise LLMError(Failure("llm", kind, "provider returned failed response", attempts=attempts, detail={"error_code": code[:100]}))

    def _stream(self, stream, on_delta, responses, attempts) -> Completion:
        parts: list[str] = []
        usage = None
        final_response = None
        provider_terminal: dict[str, Any] = {}
        provider_usage: dict[str, Any] = {}
        if responses:
            decoded_events = getattr(stream, "stream_iterator", None)
            if decoded_events is None:
                raise ConfigError("the pinned LiteLLM Responses iterator does not expose provider events")

            def preserve_provider_response():
                # SSE decoding still belongs to the SDK. Preserve the terminal
                # JSON before LiteLLM fills missing usage with a local estimate.
                for event in decoded_events:
                    try:
                        data = json.loads(event.data)
                    except (ValueError, TypeError):
                        data = {}
                    if isinstance(data, dict) and data.get("type") in (
                        "response.completed", "response.incomplete", "response.failed"
                    ):
                        provider_terminal.update(_dict(data.get("response")))
                    yield event

            stream.stream_iterator = preserve_provider_response()
        elif self._config.protocol == "anthropic":
            native = getattr(stream, "completion_stream", None)
            parser = getattr(native, "chunk_parser", None)
            if parser is None:
                raise ConfigError("the pinned LiteLLM Anthropic iterator does not expose provider chunks")

            def preserve_anthropic_usage(chunk):
                kind = chunk.get("type")
                if kind == "message_start":
                    message = _dict(chunk.get("message"))
                    native_usage = message.get("usage")
                    if isinstance(native_usage, dict):
                        provider_usage.update(native_usage)
                    elif "usage" in message:
                        chunk = {**chunk, "message": {k: v for k, v in message.items() if k != "usage"}}
                elif kind == "message_delta":
                    native_usage = chunk.get("usage")
                    if isinstance(native_usage, dict):
                        provider_usage.update(native_usage)
                    elif "usage" in chunk:
                        chunk = {k: v for k, v in chunk.items() if k != "usage"}
                return parser(chunk=chunk)

            native.chunk_parser = preserve_anthropic_usage
        event_count = 0
        finished = False
        last_text = time.monotonic()
        for chunk in self._events(stream, lambda: last_text, attempts):
            data = _dict(chunk)
            event_count += 1
            if responses:
                event = data.get("type")
                if event == "response.failed":
                    self._check_response(_dict(data.get("response")), attempts)
                piece = data.get("delta") if event in ("response.output_text.delta", "response.reasoning_text.delta", "response.reasoning_summary_text.delta") else None
                if event == "response.output_text.delta" and isinstance(piece, str):
                    parts.append(piece)
                if event in ("response.completed", "response.incomplete"):
                    final_response = _dict(data.get("response"))
                    finished = True
                pieces = [piece] if isinstance(piece, str) and piece else []
            else:
                choices = data.get("choices") or []
                choice = choices[0] if choices else {}
                delta = _dict(choice.get("delta"))
                piece = delta.get("content")
                if isinstance(piece, str):
                    parts.append(piece)
                pieces = [p for p in (piece, delta.get("reasoning_content")) if isinstance(p, str) and p]
                finished = finished or bool(choice.get("finish_reason"))
            if pieces:
                last_text = time.monotonic()
                for piece in pieces:
                    on_delta(piece)
            elif time.monotonic() - last_text > STREAM_STALL_SECONDS:
                raise LLMError(Failure("llm", "timeout", "stream produced no text for too long", attempts=attempts))
        if responses:
            usage = _usage(provider_terminal.get("usage"))
        elif self._config.protocol == "anthropic":
            usage = _usage(provider_usage, anthropic=True)
            finished = getattr(stream, "received_finish_reason", None) is not None
        else:
            # The SDK's final emitted usage can be estimated. Its retained provider
            # chunks are the source for reported usage; never use the final estimate.
            for chunk in getattr(stream, "chunks", []):
                native_usage = _dict(chunk).get("usage")
                if native_usage is not None:
                    usage = _usage(native_usage)
            finished = getattr(stream, "received_finish_reason", None) is not None
        text = "".join(parts)
        if not text and final_response:
            text = "".join(p.get("text", "") for item in final_response.get("output", []) if item.get("type") == "message" for p in item.get("content", []) if p.get("type") == "output_text")
        if not text or not finished:
            raise LLMError(Failure("llm", "incomplete", "stream ended without a complete answer", attempts=attempts))
        return Completion(text, usage, {
            "stream": True,
            "format": "provider-response" if responses else "litellm-normalized",
            "response": provider_terminal if responses else {"text": text},
            "data_events": event_count,
        })

    @staticmethod
    def _events(stream, last_text, attempts):
        """Observe SDK events with a deadline, including SDK-suppressed heartbeats.

        Parsing remains inside LiteLLM. The bounded queue neither stores raw SSE
        nor treats producer exceptions as normal EOF.
        """
        messages = queue.Queue(maxsize=8)
        stopped = threading.Event()
        end = object()

        def send(value):
            while not stopped.is_set():
                try:
                    messages.put(value, timeout=0.1)
                    return True
                except queue.Full:
                    pass
            return False

        def pump():
            try:
                for value in stream:
                    if not send(value):
                        return
            except Exception as exc:
                send(exc)
            finally:
                send(end)

        threading.Thread(target=pump, daemon=True).start()
        try:
            while True:
                remaining = STREAM_STALL_SECONDS - (time.monotonic() - last_text())
                try:
                    item = messages.get(timeout=max(remaining, 0.0))
                except queue.Empty:
                    raise LLMError(Failure("llm", "timeout", "stream produced no text for too long", attempts=attempts)) from None
                if item is end:
                    return
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            stopped.set()
            inner = getattr(stream, "completion_stream", None)
            for target in (stream, inner, getattr(stream, "response", None), getattr(inner, "response", None)):
                close = getattr(target, "close", None)
                if close is not None:
                    try:
                        close()
                    except (ValueError, RuntimeError):
                        pass
