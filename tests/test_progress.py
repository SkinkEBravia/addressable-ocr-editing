"""experiment.progress 的报告器测试。

对应 Docs/Design/11-experiment.md「运行时可观测」节：并发下状态行是
全局吞吐口径——start_cell 不得清空增量窗口，token 按 cell 累计求和。
"""

from __future__ import annotations

import threading
import time
from io import StringIO

from agent import Budget, Session, Turn
from experiment.progress import NullProgress, RichProgress, build_reporter
from llm import Completion, Message, Usage


def _session(task_id: str, toolset: str, out_tokens: int) -> Session:
    return Session(
        task_id=task_id,
        toolset=toolset,
        config_hash="h",
        budget=Budget(),
        turns=[
            Turn(0, (Message("user", "q"),), Completion("t", Usage(10, out_tokens)))
        ],
    )


def test_concurrent_cells_global_throughput():
    p = RichProgress(stream=StringIO(), force_terminal=False)
    p.begin(4)
    p.start_cell("a × x")
    p.delta("x" * 400)
    p.start_cell("b × x")  # 第二个 cell 启动不得清空增量窗
    line = p._status_line_locked()
    assert "tok/s/15s窗" in line  # 窗口仍在（修复前会被 start_cell 清成 "-"）
    assert "2 active" in line

    p.turn(_session("a", "x", 100))
    p.turn(_session("b", "x", 50))
    p.turn(_session("a", "x", 150))  # 同 cell 覆盖不累加
    line = p._status_line_locked()
    assert "200 out tok" in line  # 150 + 50

    p.end_cell("a × x", _session("a", "x", 150), 3.0)
    assert "1 active" in p._status_line_locked()
    p.close()


def test_serial_degrades_to_same_shape():
    p = RichProgress(stream=StringIO(), force_terminal=False)
    p.begin(1)
    p.start_cell("a × x")
    p.delta("abcd")
    assert "1 active" in p._status_line_locked()
    p.turn(_session("a", "x", 7))
    assert "7 out tok" in p._status_line_locked()
    p.close()


def test_build_reporter_and_null():
    assert isinstance(build_reporter(None), RichProgress)
    null = build_reporter("null")
    assert isinstance(null, NullProgress)
    null.begin(1)  # 全空操作不抛错
    null.close()


def test_tty_callbacks_release_lock_before_waiting_on_live():
    """TTY Live 刷新线程：持 Live lock → __rich__ 再拿 progress lock。
    worker 若持 progress lock 再 live.update（等 Live lock），锁顺序相反，
    docker -it 下 resume 风暴会卡死（进度停在已 skipped 的格、0 active）。
    """
    progress = RichProgress(stream=StringIO(), force_terminal=True)
    progress.begin(2)
    live = progress._live
    assert live is not None
    orig_update = live.update
    violations: list[str] = []

    def wrapped(renderable, *, refresh: bool = False):
        if progress._lock._is_owned():
            violations.append("live.update while holding progress lock")
        return orig_update(renderable, refresh=refresh)

    live.update = wrapped  # type: ignore[method-assign]
    progress.start_cell("a × x")
    progress.turn(_session("a", "x", 3))
    progress.end_cell("a × x", _session("a", "x", 3), 1.0)
    progress.close()
    assert violations == []


def test_tty_live_resume_storm_does_not_deadlock():
    """公开接口：多 worker 连续 end_cell 必须跨过若干 Live 帧仍能结束。"""
    finished = threading.Event()
    progress = RichProgress(stream=StringIO(), force_terminal=True)

    def run() -> None:
        progress.begin(10_000)
        stop = threading.Event()

        def hammer(i: int) -> None:
            n = 0
            while not stop.is_set():
                label = f"t{i}-{n} × x"
                progress.start_cell(label)
                progress.end_cell(label, _session(f"t{i}-{n}", "x", 1), 0.0)
                n += 1

        threads = [threading.Thread(target=hammer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        time.sleep(0.6)  # 5 fps → 至少两帧与 worker 重叠
        stop.set()
        for t in threads:
            t.join()
        progress.close()
        finished.set()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    assert finished.wait(timeout=8), "RichProgress TTY Live deadlocked"
