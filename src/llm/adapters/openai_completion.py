"""openai-completion 协议适配器：POST {base_url}/chat/completions。

对应 Docs/Design/08-llm.md「协议适配器」「错误与重试」节。

- 线格式互转与 usage 提取，不改写内容。
- 采样键缺席（None）= 不下发该参数。
- reasoning_tokens 从 usage.completion_tokens_details.reasoning_tokens 提取。
- 传输层重试：timeout / rate_limit / server，指数退避并尊重 Retry-After；
  auth / bad_response 不重试。
- 安全约束：API key 不打印、不进异常消息。
"""

from __future__ import annotations

import time

import httpx

from llm.config import ModelConfig
from llm.errors import LLMError
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
            from llm.errors import ConfigError

            raise ConfigError(
                f"reasoning_effort {config.reasoning_effort!r} 非法"
                f"（{list(_REASONING_EFFORT_VALUES)}）"
            )
        payload["reasoning_effort"] = config.reasoning_effort
    return payload


def _parse_usage(data: dict) -> Usage | None:
    """从端点 usage 字段提取；端点不返回则为 None（不做本地估算）。"""
    usage = data.get("usage")
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
    return Completion(text=text, usage=_parse_usage(data), raw=data)


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

    def complete(self, messages: list[Message]) -> Completion:
        payload = _build_payload(self._config, messages)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._config.base_url.rstrip('/')}/chat/completions"
        if self._client is not None:
            return self._request_with_retry(self._client, url, payload, headers)
        with httpx.Client(timeout=self._config.timeout) as client:
            return self._request_with_retry(client, url, payload, headers)

    def _request_with_retry(
        self,
        client: httpx.Client,
        url: str,
        payload: dict,
        headers: dict[str, str],
    ) -> Completion:
        attempts = 0
        while True:
            attempts += 1
            try:
                response = client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                if attempts > self._config.max_transport_retries:
                    raise LLMError(
                        f"超时：{type(exc).__name__}", kind="timeout", attempts=attempts
                    ) from exc
                _backoff(attempts)
                continue
            except httpx.TransportError as exc:
                if attempts > self._config.max_transport_retries:
                    raise LLMError(
                        f"网络错误：{type(exc).__name__}", kind="timeout", attempts=attempts
                    ) from exc
                _backoff(attempts)
                continue
            status = response.status_code
            if status == 429:
                if attempts > self._config.max_transport_retries:
                    raise LLMError(
                        "限流，重试耗尽", kind="rate_limit", status=status, attempts=attempts
                    )
                _backoff(attempts, response.headers.get("Retry-After"))
                continue
            if status >= 500:
                if attempts > self._config.max_transport_retries:
                    raise LLMError(
                        "服务不可用，重试耗尽", kind="server", status=status, attempts=attempts
                    )
                _backoff(attempts, response.headers.get("Retry-After"))
                continue
            if status in (401, 403):
                raise LLMError(
                    "认证失败（不可重试）", kind="auth", status=status, attempts=attempts
                )
            if status != 200:
                raise LLMError(
                    f"请求被拒绝（HTTP {status}，不可重试）",
                    kind="bad_response",
                    status=status,
                    attempts=attempts,
                )
            return _parse_completion(response, attempts=attempts)
