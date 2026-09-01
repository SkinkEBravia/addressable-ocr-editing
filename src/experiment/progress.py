"""experiment 的过程可观测：Progress 渲染器（基于 rich.Live）。

动机：LLM 实验必须能中途判断"出没出问题"（打同一文档连续 ReadTimeout 的教训）。

- TTY：`rich.live.Live` 原地重绘一个固定结构（状态行 + 最近事件 + 最近 3 行
  模型输出）——不堆积历史；行宽裁剪、Windows VT、刷新节流都由 rich 处理。
- 非 TTY（管道/重定向）：退化为事件行（start/done/failed），不喷 ANSI。
- 线程安全：状态更新走内部锁，Live 的渲染线程安全由 rich 保证。

显示内容：进度计数、当前 cell（task × toolset）、轮数、墙钟、
输出 token 数与 TPS（usage 到达前用增量块数估算，标注 ~）。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any, TextIO

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

__all__ = ["Progress", "NullProgress"]


class NullProgress:
    """空实现：run_experiment 的缺省（库内调用不渲染）。"""

    def begin(self, total: int) -> None: ...
    def start_cell(self, label: str) -> None: ...
    def delta(self, text: str) -> None: ...
    def turn(self, usage: Any) -> None: ...
    def end_cell(self, label: str, status: str, usage: Any, elapsed_s: float) -> None: ...


class Progress:
    def __init__(
        self,
        stream: TextIO | None = None,
        tail_lines: int = 3,
        *,
        force_terminal: bool | None = None,  # 测试用：强制 TTY 路径
    ) -> None:
        self._stream = stream or sys.stderr
        if force_terminal is None:
            force_terminal = bool(getattr(self._stream, "isatty", lambda: False)())
        # TTY 判定以 isatty() 为准：沙箱 / 嵌入式 shell 常把 TERM 设成 dumb，
        # rich 会因此禁用 Live 渲染（静默不输出）——确认真 TTY 后剔除误导的 TERM。
        environ = dict(os.environ)
        if force_terminal and environ.get("TERM", "").lower() in ("dumb", "unknown"):
            del environ["TERM"]
        self._console = Console(
            file=self._stream,
            highlight=False,
            force_terminal=force_terminal,
            force_interactive=force_terminal,  # Windows 无 TERM，否则 Live 不渲染
            _environ=environ,  # rich 内部参数（rich 15 锁定），隔离 TERM 误判
        )
        self._tty = self._console.is_terminal
        self._tail_lines = tail_lines
        self._lock = threading.Lock()
        self._live: Live | None = None
        self._total = 0
        self._done = 0
        self._label = ""
        self._turns = 0
        self._cell_start = 0.0
        self._out_tokens = 0  # usage 累计（精确）
        self._delta_chunks = 0  # 增量块数（估算）
        self._tail: list[str] = []
        self._buf = ""
        self._last_event = ""

    # -- 生命周期 -------------------------------------------------------------

    def begin(self, total: int) -> None:
        with self._lock:
            self._total = total
            if self._tty and self._live is None:
                self._live = Live(
                    self._renderable_locked(),
                    console=self._console,
                    refresh_per_second=5,
                    transient=True,  # 结束后清掉刷新块，终态由事件行/汇总给出
                )
                self._live.start()

    def close(self) -> None:
        """停止 Live（实验结束时调用；幂等）。"""
        with self._lock:
            if self._live is not None:
                self._live.stop()
                self._live = None

    # -- 事件 ---------------------------------------------------------------

    def start_cell(self, label: str) -> None:
        with self._lock:
            self._label = label
            self._turns = 0
            self._cell_start = time.monotonic()
            self._out_tokens = 0
            self._delta_chunks = 0
            self._tail = []
            self._buf = ""
            if self._tty:
                self._refresh_locked()
            else:
                self._stream.write(f"[start] {label}\n")
                self._stream.flush()

    def delta(self, text: str) -> None:
        with self._lock:
            self._delta_chunks += 1
            self._buf += text
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                self._tail.append(line)
            if len(self._tail) > self._tail_lines:
                self._tail = self._tail[-self._tail_lines :]
            if self._tty:
                self._refresh_locked()

    def turn(self, usage: Any) -> None:
        with self._lock:
            self._turns += 1
            if usage is not None:
                self._out_tokens += usage.output_tokens
            if self._tty:
                self._refresh_locked()

    def end_cell(self, label: str, status: str, usage: Any, elapsed_s: float) -> None:
        with self._lock:
            self._done += 1
            tokens = usage.output_tokens if usage is not None else 0
            tps = tokens / elapsed_s if elapsed_s > 0 else 0.0
            event = f"{label} -> {status} ({elapsed_s:.0f}s, {tokens} out tok, {tps:.1f} tok/s)"
            if self._tty:
                self._last_event = event  # 进刷新块，不另起历史行
                self._refresh_locked()
            else:
                self._stream.write(f"[{self._done}/{self._total}] {event}\n")
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

    def _renderable_locked(self) -> Group:
        tail = (self._tail + [self._buf])[-self._tail_lines :]
        lines = [
            Text(self._status_line_locked()),
            Text(f"  最近: {self._last_event}" if self._last_event else " "),
            *(Text(line if line else " ") for line in tail),
        ]
        # 固定行数：不足补空行，重绘区域高度恒定
        while len(lines) < 2 + self._tail_lines:
            lines.append(Text(" "))
        return Group(*lines)

    def _refresh_locked(self) -> None:
        if self._live is not None:
            self._live.update(self._renderable_locked(), refresh=True)
