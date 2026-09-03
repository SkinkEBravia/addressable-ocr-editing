"""experiment 的运行时报告器：可插拔接口与内建实现。

对应 Docs/Design/11-experiment.md「运行时可观测」节。

接口（`ProgressReporter`）是唯一契约：run_experiment 只面向它编程，
实现可整体替换——用户自研组件、rich、纯日志均可。

- `RichProgress`（默认）：rich.Live 原地刷新状态行（进度/轮次/墙钟/out tok/TPS）
  + 最近事件行；非 TTY 退化为事件行。声明了 `delta(text)`：run 层在流式开启时
  把增量喂给它——状态行显示滚动 TPS 估值（增量字符 ÷ 4，标 `~`；精确值仍以
  轮末端点 usage 为准）。
- `NullProgress`：全空操作，库内调用缺省。
- 流式与否是显式运行参数（run_experiment 的 stream），报告器只是订阅者。
"""

from __future__ import annotations

import importlib
import sys
import threading
import time
from typing import Any, Protocol, TextIO, runtime_checkable

from agent import Session

__all__ = ["ProgressReporter", "NullProgress", "RichProgress", "build_reporter"]


@runtime_checkable
class ProgressReporter(Protocol):
    """实验运行时报告器契约。全部为观察回调，不得影响实验语义。

    - `begin(total)`：矩阵开始，告知 cell 总数。
    - `start_cell(label)`：一个 cell 开始（label = "task_id × toolset"）。
    - `turn(session)`：一轮完成；usage 从 session 派生。
    - `end_cell(label, session, elapsed_s)`：cell 终态
      （done / budget_exceeded / failed:<kind> / resumed）。
    - `close()`：运行结束（含 Ctrl+C 的 finally），释放终端资源。

    可选能力：`delta(text: str)` —— 流式观察订阅。实现了才会被喂增量。
    """

    def begin(self, total: int) -> None: ...
    def start_cell(self, label: str) -> None: ...
    def turn(self, session: Session) -> None: ...
    def end_cell(self, label: str, session: Session, elapsed_s: float) -> None: ...
    def close(self) -> None: ...


class NullProgress:
    """空实现：run_experiment 的缺省（库内调用不渲染）。"""

    def begin(self, total: int) -> None: ...
    def start_cell(self, label: str) -> None: ...
    def turn(self, session: Session) -> None: ...
    def end_cell(self, label: str, session: Session, elapsed_s: float) -> None: ...
    def close(self) -> None: ...


class RichProgress:
    """基于 rich.Live 的报告器：状态行 + 最近事件行，原地刷新不堆历史。

    只计数不预览——模型输出文本不进终端（输出预览已明确不做）。
    """

    # 估值口径：英文/代码约 4 字符 ≈ 1 token；仅作活动指示，不进报告
    _CHARS_PER_TOKEN_EST = 4

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
        self._lock = threading.RLock()  # Live 渲染回调会重入（update 时持锁渲染）
        self._live: Any = None
        self._total = 0
        self._done = 0
        self._label = ""
        self._turns = 0
        self._cell_start = 0.0
        self._out_tokens = 0  # usage 累计（端点精确值）
        self._stream_chars = 0  # 本轮流式增量字符（估值用）
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
            self._stream_chars = 0
            if self._tty:
                self._refresh_locked()
            else:
                self._stream.write(f"[start] {label}\n")
                self._stream.flush()

    def delta(self, text: str) -> None:
        """流式观察：只计数（滚动 TPS 估值），不渲染模型输出文本。"""
        with self._lock:
            self._stream_chars += len(text)

    def turn(self, session: Session) -> None:
        with self._lock:
            self._turns = len(session.turns)
            usage = session.usage
            if usage is not None:
                self._out_tokens = usage.output_tokens
            self._stream_chars = 0  # 新轮归零
            if self._tty:
                self._refresh_locked()

    def end_cell(self, label: str, session: Session, elapsed_s: float) -> None:
        with self._lock:
            self._done += 1
            usage = session.usage
            tokens = usage.output_tokens if usage is not None else 0
            tps = tokens / elapsed_s if elapsed_s > 0 else 0.0
            event = (
                f"{label} -> {session.status} "
                f"({elapsed_s:.0f}s, {tokens} out tok, {tps:.1f} tok/s)"
            )
            if session.failure is not None:
                event += f" [{session.failure.kind}: {session.failure.message[:80]}]"
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
            # 有轮末端点值：精确 TPS
            tps = f"{self._out_tokens / elapsed:.1f} tok/s" if elapsed > 0 else "-"
        elif self._stream_chars:
            # 轮内流式增量：估值（字符 ÷ 4），只作活动指示
            est = self._stream_chars / self._CHARS_PER_TOKEN_EST
            tps = f"~{est / elapsed:.1f} tok/s" if elapsed > 0 else "~-"
        else:
            tps = "-"
        return (
            f"[{self._done}/{self._total}] {self._label} | turn {self._turns + 1} "
            f"| {elapsed:.0f}s | {self._out_tokens} out tok | {tps}"
        )

    def _renderable_locked(self) -> Any:
        progress = self

        class _Dynamic:
            def __rich__(self) -> Any:
                from rich.console import Group
                from rich.text import Text

                with progress._lock:
                    event = (
                        f"  最近: {progress._last_event}" if progress._last_event else " "
                    )
                    return Group(
                        Text(progress._status_line_locked()), Text(event)
                    )

        return _Dynamic()

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
