"""experiment 的过程可观测：Progress 渲染器。

动机：LLM 实验必须能中途判断"出没出问题"（打同一文档连续 ReadTimeout 的教训）。

- TTY：状态行 + 最近 3 行模型输出（流式增量）原地刷新。
- 非 TTY（管道/重定向）：退化为事件行（start/done/failed），不刷屏。
- 线程安全：并发 workers 下多路增量汇入同一窗口。

显示内容：进度计数、当前 cell（task × toolset）、轮数、墙钟、
输出 token 数与 TPS（usage 到达前用增量块数估算，标注 ~）。
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any, TextIO

__all__ = ["Progress", "NullProgress"]

_RENDER_INTERVAL_S = 0.2  # 刷新节流


class NullProgress:
    """空实现：run_experiment 的缺省（库内调用不渲染）。"""

    def begin(self, total: int) -> None: ...
    def start_cell(self, label: str) -> None: ...
    def delta(self, text: str) -> None: ...
    def turn(self, usage: Any) -> None: ...
    def end_cell(self, label: str, status: str, usage: Any, elapsed_s: float) -> None: ...


class Progress:
    def __init__(self, stream: TextIO | None = None, tail_lines: int = 3) -> None:
        self._stream = stream or sys.stderr
        self._tty = bool(getattr(self._stream, "isatty", lambda: False)())
        self._tail_lines = tail_lines
        self._lock = threading.Lock()
        self._total = 0
        self._done = 0
        self._label = ""
        self._turns = 0
        self._cell_start = 0.0
        self._out_tokens = 0  # usage 累计（精确）
        self._delta_chunks = 0  # 增量块数（估算）
        self._tail: list[str] = []
        self._buf = ""
        self._last_render = 0.0
        self._block_lines = 0  # 屏幕上当前占用行数（0 = 无活动块）

    # -- 事件 ---------------------------------------------------------------

    def begin(self, total: int) -> None:
        with self._lock:
            self._total = total

    def start_cell(self, label: str) -> None:
        with self._lock:
            self._commit_block_locked()
            self._label = label
            self._turns = 0
            self._cell_start = time.monotonic()
            self._out_tokens = 0
            self._delta_chunks = 0
            self._tail = []
            self._buf = ""
            if not self._tty:
                self._stream.write(f"[start] {label}\n")
                self._stream.flush()
            else:
                self._render_locked(force=True)

    def delta(self, text: str) -> None:
        with self._lock:
            self._delta_chunks += 1
            self._buf += text
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                self._tail.append(line)
            # 保留 tail_lines + 1 条（末行是进行中的 buf）
            if len(self._tail) > self._tail_lines:
                self._tail = self._tail[-self._tail_lines :]
            if self._tty:
                self._render_locked()

    def turn(self, usage: Any) -> None:
        with self._lock:
            self._turns += 1
            if usage is not None:
                self._out_tokens += usage.output_tokens
            if self._tty:
                self._render_locked(force=True)

    def end_cell(self, label: str, status: str, usage: Any, elapsed_s: float) -> None:
        with self._lock:
            self._done += 1
            self._commit_block_locked()
            tokens = usage.output_tokens if usage is not None else 0
            tps = tokens / elapsed_s if elapsed_s > 0 else 0.0
            self._stream.write(
                f"[{self._done}/{self._total}] {label} -> {status} "
                f"({elapsed_s:.0f}s, {tokens} out tok, {tps:.1f} tok/s)\n"
            )
            self._stream.flush()

    # -- 渲染 ---------------------------------------------------------------

    def _status_line_locked(self) -> str:
        elapsed = time.monotonic() - self._cell_start
        if self._out_tokens:
            tokens = f"{self._out_tokens} out tok"
        else:
            tokens = f"~{self._delta_chunks} out chunks"
        tps = (self._out_tokens or self._delta_chunks) / elapsed if elapsed > 0 else 0
        mark = "" if self._out_tokens else "~"
        return (
            f"[{self._done}/{self._total}] {self._label} | turn {self._turns + 1} "
            f"| {elapsed:.0f}s | {tokens} | {mark}{tps:.1f} tok/s"
        )

    def _render_locked(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_render < _RENDER_INTERVAL_S:
            return
        self._last_render = now
        lines = self._tail + [self._buf[-2000:]]  # 末行截断防超长
        block = [self._status_line_locked(), *lines[-self._tail_lines :]]
        if self._block_lines:
            self._stream.write(f"\x1b[{self._block_lines}A")  # 光标上移
        for line in block:
            self._stream.write("\r\x1b[K" + line + "\n")  # 清行重写
        self._block_lines = len(block)
        self._stream.flush()

    def _commit_block_locked(self) -> None:
        """结束当前刷新块（光标留在块尾，之后输出为普通流）。"""
        if self._tty and self._block_lines:
            self._block_lines = 0
