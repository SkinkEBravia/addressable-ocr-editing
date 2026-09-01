"""openai-completion 协议适配器：POST {base_url}/chat/completions。

对应 Docs/Design/08-llm.md「协议适配器」「错误与重试」节。

- 线格式互转与 usage 提取，不改写内容。
- 采样键缺席（None）= 不下发该参数。
- reasoning_tokens 从 usage.completion_tokens_details.reasoning_tokens 提取。
- 流式：传入 on_delta 时启用 stream（含 stream_options.include_usage），
  每个增量（content 与 reasoning_content）回调给调用方——过程可观测，
  长思考不再表现为静默挂起。
- 传输层重试：timeout / rate_limit / server，指数退避并尊重 Retry-After；
  auth / bad_response 不重试。
- 安全约束：API key 不打印、不进异常消息。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import httpx

from llm.config import ModelConfig
from llm.errors import ConfigError, LLMError
from llm.types import Completion, Message, Usage

__all__ = ["OpenAICompletionClient"]

_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_MAX_SECONDS = 60.0

_REASONING_EFFORT_VALUES = ("low", "medium", "high")


def _backoff(retry_index: int, retry_after: str | None = None) -> None:
    """指数退避（1s, 2s, 4s, ... 封顶 60s）；端点给了 Retry-After 则从其值。"""
    delay = min(_BACKOFF_MAX_SECONDS, _BACKOFF_BASE_SECONDS * 2 ** (retry_index - 1))
    if retry_after is not None:
        try:
            delay = max(delay, float(retry_after))
        except ValueError:
            pass
    time.sleep(delay)


def _build_payload(config: ModelConfig, messages: list[Message]) -> dict:
    payload: dict = {
        "model": config.model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
    }
    # 缺席 = 不下发；显式值才进线格式
    if config.temperature is not None:
        payload["temperature"] = config.temperature
    if config.reasoning_effort is not None:
        if config.reasoning_effort not in _REASONING_EFFORT_VALUES:
            raise ConfigError(
                f"reasoning_effort {config.reasoning_effort!r} 非法"
                f"（{list(_REASONING_EFFORT_VALUES)}）"
            )
        payload["reasoning_effort"] = config.reasoning_effort
    return payload


def _usage_from_dict(usage: object) -> Usage | None:
    """端点 usage 字段 -> Usage；缺失/畸形为 None（不做本地估算）。"""
    if not isinstance(usage, dict):
        return None
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None
    reasoning = None
    details = usage.get("completion_tokens_details")
    if isinstance(details, dict) and isinstance(details.get("reasoning_tokens"), int):
        reasoning = details["reasoning_tokens"]
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning,
    )


def _parse_completion(response: httpx.Response, *, attempts: int) -> Completion:
    try:
        data = response.json()
    except ValueError as exc:
        raise LLMError("响应体不是合法 JSON", kind="bad_response", attempts=attempts) from exc
    if not isinstance(data, dict):
        raise LLMError("响应体不是 JSON 对象", kind="bad_response", attempts=attempts)
    choices = data.get("choices")
    try:
        text = choices[0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(
            "响应缺少 choices[0].message.content", kind="bad_response", attempts=attempts
        ) from exc
    if not isinstance(text, str):
        raise LLMError("响应 content 不是字符串", kind="bad_response", attempts=attempts)
    return Completion(text=text, usage=_usage_from_dict(data.get("usage")), raw=data)


class _Retryable(Exception):
    """内部：可重试的传输失败（限流 / 5xx / 网络）。"""

    def __init__(self, message: str, *, kind: str, status: int | None = None,
                 retry_after: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after


class OpenAICompletionClient:
    """OpenAI Chat Completions 兼容端点的 LLMClient 实现（httpx 同步）。

    传入 ``http_client`` 时由调用方持有其生命周期，便于测试注入 mock。
    """

    def __init__(
        self,
        config: ModelConfig,
        api_key: str,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._client = http_client

    def complete(
        self,
        messages: list[Message],
        *,
        on_delta: Callable[[str], None] | None = None,
    ) -> Completion:
        payload = _build_payload(self._config, messages)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._config.base_url.rstrip('/')}/chat/completions"
        t0 = time.monotonic()
        if self._client is not None:
            comp = self._request_with_retry(self._client, url, payload, headers, on_delta)
        else:
            with httpx.Client(timeout=self._config.timeout) as client:
                comp = self._request_with_retry(client, url, payload, headers, on_delta)
        return Completion(
            text=comp.text,
            usage=comp.usage,
            raw=comp.raw,
            elapsed_s=time.monotonic() - t0,
        )

    # -- 重试循环 -----------------------------------------------------------

    def _request_with_retry(
        self,
        client: httpx.Client,
        url: str,
        payload: dict,
        headers: dict,
        on_delta: Callable[[str], None] | None,
    ) -> Completion:
        attempts = 0
        while True:
            attempts += 1
            try:
                if on_delta is None:
                    response = client.post(url, json=payload, headers=headers)
                    self._raise_for_status(response)
                    return _parse_completion(response, attempts=attempts)
                return self._stream_once(client, url, payload, headers, on_delta, attempts)
            except httpx.TimeoutException as exc:
                if attempts > self._config.max_transport_retries:
                    raise LLMError(
                        f"超时：{type(exc).__name__}", kind="timeout", attempts=attempts
                    ) from exc
                _backoff(attempts)
            except httpx.TransportError as exc:
                if attempts > self._config.max_transport_retries:
                    raise LLMError(
                        f"网络错误：{type(exc).__name__}", kind="timeout", attempts=attempts
                    ) from exc
                _backoff(attempts)
            except _Retryable as r:
                if attempts > self._config.max_transport_retries:
                    raise LLMError(
                        str(r), kind=r.kind, status=r.status, attempts=attempts
                    ) from r
                _backoff(attempts, r.retry_after)

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status == 200:
            return
        if status == 429:
            raise _Retryable(
                "限流", kind="rate_limit", status=status,
                retry_after=response.headers.get("Retry-After"),
            )
        if status >= 500:
            raise _Retryable(
                "服务不可用", kind="server", status=status,
                retry_after=response.headers.get("Retry-After"),
            )
        if status in (401, 403):
            raise LLMError("认证失败（不可重试）", kind="auth", status=status)
        raise LLMError(
            f"请求被拒绝（HTTP {status}，不可重试）", kind="bad_response", status=status
        )

    # -- 流式 ---------------------------------------------------------------

    def _stream_once(
        self,
        client: httpx.Client,
        url: str,
        payload: dict,
        headers: dict,
        on_delta: Callable[[str], None],
        attempts: int,
    ) -> Completion:
        payload = {
            **payload,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        text_parts: list[str] = []
        usage_dict: dict | None = None
        with client.stream("POST", url, json=payload, headers=headers) as response:
            self._raise_for_status(response)
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue  # 半行 / 心跳，跳过
                if isinstance(obj.get("usage"), dict):
                    usage_dict = obj["usage"]
                for choice in obj.get("choices") or []:
                    delta = choice.get("delta") or {}
                    piece = delta.get("content")
                    if isinstance(piece, str) and piece:
                        text_parts.append(piece)
                        on_delta(piece)
                    thinking = delta.get("reasoning_content")
                    if isinstance(thinking, str) and thinking:
                        on_delta(thinking)  # 思考过程也可观测
        return Completion(
            text="".join(text_parts),
            usage=_usage_from_dict(usage_dict),
            raw={"stream": True, "usage": usage_dict},
        )
