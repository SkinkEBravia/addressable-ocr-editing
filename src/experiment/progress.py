"""experiment 的运行时报告器：可插拔接口与内建实现。

对应 Docs/Design/11-experiment.md「运行时可观测」节。

接口（`ProgressReporter`）是唯一契约：run_experiment 只面向它编程，
实现可整体替换——用户自研组件、rich、纯日志均可。

- `RichProgress`（默认）：rich.Live 原地刷新状态行（进度/轮次/墙钟/out tok/TPS）
  + 最近事件行；非 TTY 退化为事件行。
- `NullProgress`：全空操作，库内调用缺省。
- 流式增量显示（模型输出尾部滚动）**已搁置**：协议里不留 `delta`；
  实现者声明了 `delta(text)` 才会被接入（run 层用 `getattr` 探测），
  否则走非流式请求。
"""

from __future__ import annotations

import importlib
import sys
import threading
import time
from typing import Any, Protocol, TextIO, runtime_checkable

from llm.types import Usage

__all__ = ["ProgressReporter", "NullProgress", "RichProgress", "build_reporter"]


@runtime_checkable
class ProgressReporter(Protocol):
    """实验运行时报告器契约。全部为观察回调，不得影响实验语义。

    - `begin(total)`：矩阵开始，告知 cell 总数。
    - `start_cell(label)`：一个 cell 开始（label = "task_id × toolset"）。
    - `turn(usage)`：一轮完成；usage 为端点计数，None = 端点未返回。
    - `end_cell(label, status, usage, elapsed_s)`：cell 终态
      （done / failed[:kind] / resumed），usage 为该 cell 合计。
    - `close()`：运行结束（含 Ctrl+C 的 finally），释放终端资源。

    可选能力：`delta(text: str)` —— 流式观察通道（搁置中）。实现了才接入。
    """

    def begin(self, total: int) -> None: ...
    def start_cell(self, label: str) -> None: ...
    def turn(self, usage: Usage | None) -> None: ...
    def end_cell(
        self, label: str, status: str, usage: Usage | None, elapsed_s: float
    ) -> None: ...
    def close(self) -> None: ...


class NullProgress:
    """空实现：run_experiment 的缺省（库内调用不渲染）。"""

    def begin(self, total: int) -> None: ...
    def start_cell(self, label: str) -> None: ...
    def turn(self, usage: Any) -> None: ...
    def end_cell(self, label: str, status: str, usage: Any, elapsed_s: float) -> None: ...
    def close(self) -> None: ...


class RichProgress:
    """基于 rich.Live 的报告器：状态行 + 最近事件行，原地刷新不堆历史。

    `tail_lines` / `force_terminal` 预留给自研实现对齐调试；本实现不使用
    tail（流式尾部显示已搁置）。
    """

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        force_terminal: bool | None = None,  # 测试用：强制 TTY 路径
    ) -> None:
        import os

        from rich.console import Console

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
        self._tty = force_terminal
        self._lock = threading.Lock()
        self._live: Any = None
        self._total = 0
        self._done = 0
        self._label = ""
        self._turns = 0
        self._cell_start = 0.0
        self._out_tokens = 0  # usage 累计（端点精确值）
        self._last_event = ""

    # -- 生命周期 -------------------------------------------------------------

    def begin(self, total: int) -> None:
        with self._lock:
            self._total = total
            if self._tty and self._live is None:
                from rich.live import Live

                self._live = Live(
                    self._renderable_locked(),
                    console=self._console,
                    refresh_per_second=5,
                    transient=True,  # 结束后清掉刷新块，不留历史
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
            if self._tty:
                self._refresh_locked()
            else:
                self._stream.write(f"[start] {label}\n")
                self._stream.flush()

    def turn(self, usage: Usage | None) -> None:
        with self._lock:
            self._turns += 1
            if usage is not None:
                self._out_tokens += usage.output_tokens
            if self._tty:
                self._refresh_locked()

    def end_cell(
        self, label: str, status: str, usage: Usage | None, elapsed_s: float
    ) -> None:
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
        tps = self._out_tokens / elapsed if elapsed > 0 else 0.0
        return (
            f"[{self._done}/{self._total}] {self._label} | turn {self._turns + 1} "
            f"| {elapsed:.0f}s | {self._out_tokens} out tok | {tps:.1f} tok/s"
        )

    def _renderable_locked(self) -> Any:
        from rich.console import Group
        from rich.text import Text

        event = f"  最近: {self._last_event}" if self._last_event else " "
        return Group(Text(self._status_line_locked()), Text(event))

    def _refresh_locked(self) -> None:
        if self._live is not None:
            self._live.update(self._renderable_locked(), refresh=True)


def build_reporter(name: str | None) -> ProgressReporter:
    """按名字构造报告器。

    - None / "rich"：`RichProgress`（默认）。
    - "null"：`NullProgress`。
    - "module:Class"：动态导入自研实现（可插拔入口）。
    """
    if name in (None, "rich"):
        return RichProgress()
    if name == "null":
        return NullProgress()
    if ":" in name:
        module_name, _, class_name = name.partition(":")
        cls = getattr(importlib.import_module(module_name), class_name)
        reporter = cls()
        if not isinstance(reporter, ProgressReporter):
            raise TypeError(f"{name} 未实现 ProgressReporter 接口")
        return reporter
    raise ValueError(f"未知报告器 {name!r}（可选：rich / null / module:Class）")
