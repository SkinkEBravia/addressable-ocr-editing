"""协议适配器共用的传输层：重试驱动、退避、HTTP 状态分类。

对应 Docs/Design/08-llm.md「错误」节。

- 重试通道（timeout / rate_limit / server）在 client 内完成：指数退避，
  尊重端点 Retry-After，上限 max_transport_retries。
- auth / rejected / protocol_mismatch / incomplete 不进重试通道，直接失败。
- 安全约束：API key 不打印、不进异常消息与 Failure detail。
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from llm.config import ModelConfig
from llm.errors import Failure, LLMError
from llm.types import Completion

__all__ = ["Retryable", "backoff", "raise_for_status", "call_with_retries", "iter_sse_data_lines"]

_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_MAX_SECONDS = 60.0
_BODY_EXCERPT = 300  # rejected 的 detail 里 body 摘录长度上限


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


def raise_for_status(response: httpx.Response, *, attempts: int) -> None:
    """HTTP 状态分类：2xx 放行；429/5xx 进重试通道；401/403 auth；其余 rejected。"""
    match response.status_code:
        case s if 200 <= s < 300:
            return
        case 429:
            raise Retryable(
                "限流",
                kind="rate_limit",
                status=429,
                retry_after=response.headers.get("Retry-After"),
            )
        case s if s >= 500:
            raise Retryable(
                "服务不可用",
                kind="server",
                status=s,
                retry_after=response.headers.get("Retry-After"),
            )
        case 401 | 403 as s:
            raise LLMError(
                Failure(
                    stage="llm",
                    kind="auth",
                    message="认证失败（不可重试）",
                    http_status=s,
                    attempts=attempts,
                )
            )
        case s:
            raise LLMError(
                Failure(
                    stage="llm",
                    kind="rejected",
                    message=f"请求被拒绝（HTTP {s}，不可重试）",
                    http_status=s,
                    attempts=attempts,
                    detail={"body_excerpt": response.text[:_BODY_EXCERPT]},
                )
            )


def call_with_retries(
    config: ModelConfig, fn: Callable[[int], Completion]
) -> Completion:
    """重试驱动：fn(attempts) 执行一次调用；重试通道失败按指数退避重发。

    LLMError（失败通道）原样上浮；此处只补录 elapsed_s。
    """
    t0 = time.monotonic()
    attempts = 0
    while True:
        attempts += 1
        try:
            return fn(attempts)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempts > config.max_transport_retries:
                prefix = "超时" if isinstance(exc, httpx.TimeoutException) else "网络错误"
                detail = f": {exc}" if isinstance(exc, httpx.TransportError) else ""
                raise LLMError(
                    Failure(
                        stage="llm",
                        kind="timeout",
                        message=f"{prefix}：{type(exc).__name__}{detail}",
                        attempts=attempts,
                        elapsed_s=time.monotonic() - t0,
                    )
                ) from exc
            backoff(attempts)
        except Retryable as r:
            if attempts > config.max_transport_retries:
                raise LLMError(
                    Failure(
                        stage="llm",
                        kind=r.kind,
                        message=str(r),
                        http_status=r.status,
                        attempts=attempts,
                        elapsed_s=time.monotonic() - t0,
                    )
                ) from r
            backoff(attempts, r.retry_after)
        except LLMError as exc:
            if exc.failure.elapsed_s is None:
                raise LLMError(
                    Failure(
                        stage=exc.failure.stage,
                        kind=exc.failure.kind,
                        message=exc.failure.message,
                        http_status=exc.failure.http_status,
                        attempts=attempts,
                        elapsed_s=time.monotonic() - t0,
                        detail=exc.failure.detail,
                    )
                ) from exc
            raise


def iter_sse_data_lines(response: httpx.Response):
    """迭代 SSE 流的 data 载荷（跳过 event 行 / 心跳 / [DONE]）。"""
    for line in response.iter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        yield data
