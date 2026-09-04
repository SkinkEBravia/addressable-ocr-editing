"""experiment.progress 的报告器测试。

对应 Docs/Design/11-experiment.md「运行时可观测」节：并发下状态行是
全局吞吐口径——start_cell 不得清空增量窗口，token 按 cell 累计求和。
"""

from __future__ import annotations

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
