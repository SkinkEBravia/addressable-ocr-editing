"""协议适配器共用的传输层：重试驱动、退避、HTTP 状态分类、SSE 停滞看门狗。

对应 Docs/Design/08-llm.md「错误」节。

- 重试通道（timeout / rate_limit / server）在 client 内完成：指数退避，
  尊重端点 Retry-After，上限 max_transport_retries。
- auth / rejected / protocol_mismatch / incomplete 不进重试通道，直接失败。
- 流式停滞看门狗：距上一条 SSE **data 行**超过 STREAM_STALL_SECONDS 即掐流，
  以 Retryable(kind="timeout") 进重试通道（心跳注释行不重置计时）。
- 可观测性：重试 / 停滞 / 重试耗尽都写 logging（logger 名 "llm.transport"），
  experiment CLI 把 "llm" logger 落到 <out>/logs/llm.log。
- 安全约束：API key 不打印、不进异常消息与 Failure detail。
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable, Iterator

import httpx

from llm.config import ModelConfig
from llm.errors import Failure, LLMError
from llm.types import Completion

__all__ = [
    "Retryable",
    "DeltaStallWatchdog",
    "STREAM_STALL_SECONDS",
    "backoff",
    "raise_for_status",
    "call_with_retries",
    "iter_sse_data_lines",
]

logger = logging.getLogger("llm.transport")

STREAM_STALL_SECONDS = 300.0  # 距上一条 SSE data 行的停滞上限（秒）

_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_MAX_SECONDS = 60.0
_BODY_EXCERPT = 300  # rejected 的 detail 里 body 摘录长度上限


def _backoff_delay(retry_index: int, retry_after: str | None = None) -> float:
    """指数退避时长（1s, 2s, 4s, ... 封顶 60s）；端点给了 Retry-After 则从其值。"""
    delay = min(_BACKOFF_MAX_SECONDS, _BACKOFF_BASE_SECONDS * 2 ** (retry_index - 1))
    if retry_after is not None:
        try:
            delay = max(delay, float(retry_after))
        except ValueError:
            pass
    return delay


def backoff(retry_index: int, retry_after: str | None = None) -> None:
    """按 _backoff_delay 的时长睡眠。"""
    time.sleep(_backoff_delay(retry_index, retry_after))


class Retryable(Exception):
    """内部：可重试的传输失败（限流 / 5xx / 网络 / 流式停滞）。"""

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
                logger.error(
                    "model=%s 重试耗尽 kind=timeout attempts=%d: %s",
                    config.name, attempts, exc,
                )
                raise LLMError(
                    Failure(
                        stage="llm",
                        kind="timeout",
                        message=f"{prefix}：{type(exc).__name__}{detail}",
                        attempts=attempts,
                        elapsed_s=time.monotonic() - t0,
                    )
                ) from exc
            delay = _backoff_delay(attempts)
            logger.warning(
                "model=%s attempt=%d kind=timeout: %s — %.0fs 后重试",
                config.name, attempts, exc, delay,
            )
            backoff(attempts)
        except Retryable as r:
            if attempts > config.max_transport_retries:
                logger.error(
                    "model=%s 重试耗尽 kind=%s attempts=%d: %s",
                    config.name, r.kind, attempts, r,
                )
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
            delay = _backoff_delay(attempts, r.retry_after)
            logger.warning(
                "model=%s attempt=%d kind=%s: %s — %.0fs 后重试",
                config.name, attempts, r.kind, r, delay,
            )
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


_EOS = object()  # 流结束哨兵


class DeltaStallWatchdog:
    """输出增量级停滞检测：专治「data 事件还在来，但文本增量归零」。

    行级看门狗（iter_sse_data_lines 的 stall_timeout）守的是连接活没活；
    本类守的是模型有没有在产出——端点的心跳 data 事件（in_progress / 空
    delta）会让行级看门狗永远满意，只有增量级检测能识别这种挂死。

    用法：流开始即建；每个非空文本增量 feed()；每条 data 事件 check()。
    """

    def __init__(
        self,
        timeout: float,
        *,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._timeout = timeout
        self._now = now
        self._last = now()

    def feed(self) -> None:
        """标记一次输出增量（非空 delta）。"""
        self._last = self._now()

    def stalled_seconds(self) -> float:
        return self._now() - self._last

    def check(self, *, context: str = "") -> None:
        """超过阈值抛 Retryable(kind="timeout")，进重试通道。"""
        gap = self.stalled_seconds()
        if gap <= self._timeout:
            return
        logger.warning(
            "输出停滞：%.0fs 无文本增量（data 事件仍在来%s），掐流重试",
            gap, f"，{context}" if context else "",
        )
        raise Retryable(
            f"输出停滞：{gap:.0f}s 无文本增量"
            + (f"（{context}）" if context else ""),
            kind="timeout",
        )


def _data_from_line(line: str) -> str | None:
    """SSE 行 -> data 载荷；event 行 / 心跳注释 / [DONE] 返回 None。"""
    if not line.startswith("data:"):
        return None
    data = line[5:].strip()
    if not data or data == "[DONE]":
        return None
    return data


def iter_sse_data_lines(
    response: httpx.Response, *, stall_timeout: float | None = None
) -> Iterator[str]:
    """迭代 SSE 流的 data 载荷（跳过 event 行 / 心跳 / [DONE]）。

    stall_timeout 非空时启用停滞看门狗：距上一条 **data 行**超过该秒数
    （心跳注释行不重置计时）即关闭响应并抛 Retryable(kind="timeout")，
    由 call_with_retries 走重试通道。实现：pump 线程读行进队列，消费端
    按「距上条 data 的剩余额度」等队列。
    """
    if stall_timeout is None:
        for line in response.iter_lines():
            if (data := _data_from_line(line)) is not None:
                yield data
        return

    q: queue.Queue = queue.Queue()

    def pump() -> None:
        try:
            for line in response.iter_lines():
                q.put(line)
        except Exception:
            # 响应被消费端关闭 / 网络断：以哨兵收尾，消费端正常结束
            pass
        finally:
            q.put(_EOS)

    threading.Thread(target=pump, daemon=True).start()
    n_data = 0
    last_data = time.monotonic()
    while True:
        wait = stall_timeout - (time.monotonic() - last_data)
        try:
            item = q.get(timeout=max(wait, 0.0))
        except queue.Empty:
            logger.warning(
                "流式停滞：%.0fs 无 data 事件（已收 %d 条），掐流重试",
                stall_timeout, n_data,
            )
            response.close()  # 掐流让 pump 线程退出
            raise Retryable(
                f"流式停滞：{stall_timeout:.0f}s 无 data 事件（已收 {n_data} 条）",
                kind="timeout",
            )
        if item is _EOS:
            return
        if (data := _data_from_line(item)) is not None:
            n_data += 1
            last_data = time.monotonic()
            yield data
