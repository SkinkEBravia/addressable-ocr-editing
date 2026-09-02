"""协议适配器共用的传输层：重试驱动、退避、HTTP 状态分类。

对应 Docs/Design/08-llm.md「错误与重试」节。

- 传输层重试（timeout / rate_limit / server）在 client 内完成：指数退避，
  尊重端点 Retry-After，上限 max_transport_retries。
- auth / bad_response 不重试。
- 安全约束：API key 不打印、不进异常消息。
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from llm.config import ModelConfig
from llm.errors import LLMError
from llm.types import Completion

__all__ = ["Retryable", "backoff", "raise_for_status", "call_with_retries"]

_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_MAX_SECONDS = 60.0


def backoff(retry_index: int, retry_after: str | None = None) -> None:
    """指数退避（1s, 2s, 4s, ... 封顶 60s）；端点给了 Retry-After 则从其值。"""
    delay = min(_BACKOFF_MAX_SECONDS, _BACKOFF_BASE_SECONDS * 2 ** (retry_index - 1))
    if retry_after is not None:
        try:
            delay = max(delay, float(retry_after))
        except ValueError:
            pass
    time.sleep(delay)


class Retryable(Exception):
    """内部：可重试的传输失败（限流 / 5xx / 网络）。"""

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        status: int | None = None,
        retry_after: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after


def raise_for_status(response: httpx.Response) -> None:
    """HTTP 状态分类：2xx 放行；429/5xx 可重试；401/403 auth；其余 bad_response。"""
    status = response.status_code
    if 200 <= status < 300:
        return
    if status == 429:
        raise Retryable(
            "限流",
            kind="rate_limit",
            status=status,
            retry_after=response.headers.get("Retry-After"),
        )
    if status >= 500:
        raise Retryable(
            "服务不可用",
            kind="server",
            status=status,
            retry_after=response.headers.get("Retry-After"),
        )
    if status in (401, 403):
        raise LLMError("认证失败（不可重试）", kind="auth", status=status)
    raise LLMError(
        f"请求被拒绝（HTTP {status}）", kind="bad_response", status=status
    )


def call_with_retries(
    config: ModelConfig, fn: Callable[[int], Completion]
) -> Completion:
    """重试驱动：fn(attempts) 执行一次调用；可重试失败按指数退避重发。"""
    attempts = 0
    while True:
        attempts += 1
        try:
            return fn(attempts)
        except httpx.TimeoutException as exc:
            if attempts > config.max_transport_retries:
                raise LLMError(
                    f"超时：{type(exc).__name__}", kind="timeout", attempts=attempts
                ) from exc
            backoff(attempts)
        except httpx.TransportError as exc:
            if attempts > config.max_transport_retries:
                raise LLMError(
                    f"网络错误：{type(exc).__name__}", kind="timeout", attempts=attempts
                ) from exc
            backoff(attempts)
        except Retryable as r:
            if attempts > config.max_transport_retries:
                raise LLMError(
                    str(r), kind=r.kind, status=r.status, attempts=attempts
                ) from r
            backoff(attempts, r.retry_after)


def iter_sse_data_lines(response: httpx.Response):
    """迭代 SSE 流的 data 载荷（跳过 event 行 / 心跳 / [DONE]）。"""
    for line in response.iter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        yield data
