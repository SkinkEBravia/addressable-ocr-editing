"""toolsets 的 loop 行为测试（Docs/Design/09-tools.md「验收」）。"""

from __future__ import annotations

from pathlib import Path

from llm import StubClient
from toolsets import REGISTRY, Budget, run_toolset


class _Task:
    def __init__(self, text: str, meta: dict | None = None):
        self.input = text
        self.meta = meta or {}


def test_noop_passthrough(tmp_path: Path):
    ts = REGISTRY["noop"]()
    r = run_toolset(StubClient([]), _Task("as is"), ts, Budget(), "INSTR", tmp_path / "a")
    assert r.status == "done"
    assert r.output == "as is"
    assert r.turns == ()


def test_rewrite_single_turn_json_extraction(tmp_path: Path):
    ts = REGISTRY["rewrite"]()
    stub = StubClient(['{"ocr_postcorrection_output": "fixed"}'])
    r = run_toolset(stub, _Task("bad"), ts, Budget(max_turns=1), "INSTR", tmp_path / "b")
    assert r.status == "done"
    assert r.output == "fixed"
    assert len(r.turns) == 1
    # 提示词组装（09 规则 1）：system = instruction + clause；user = 输入呈现
    system, user = stub.calls[0]
    assert system.role == "system"
    assert system.content.startswith("INSTR\n\n") and ts.prompt_clause in system.content
    assert user.role == "user"
    assert "--- INPUT" in user.content and "bad" in user.content


def test_patch_error_feedback_then_done(tmp_path: Path):
    """工具报错即对话反馈：坏 patch 的 feedback 进下一轮，无独立重试路径。"""
    ts = REGISTRY["patch"]()
    stub = StubClient(['replace(b1, "nope", "x")', 'replace(b1, "teh", "the")', "done()"])
    r = run_toolset(
        stub, _Task("teh quick fox"), ts, Budget(max_turns=5), "INSTR", tmp_path / "c"
    )
    assert r.status == "done"
    assert r.output == "the quick fox"
    assert len(r.turns) == 3
    # 第一轮的失败反馈出现在第二轮的请求里
    assert "PATTERN_NOT_FOUND" in stub.calls[1][-1].content


def test_patch_parse_error_feedback(tmp_path: Path):
    ts = REGISTRY["patch"]()
    stub = StubClient(["", "done()"])  # 空响应 -> ParseError
    r = run_toolset(
        stub, _Task("fine"), ts, Budget(max_turns=3), "INSTR", tmp_path / "d"
    )
    assert r.status == "done"
    assert r.turns[0].parse_error is not None
    assert "parse error" in stub.calls[1][-1].content


def test_budget_exceeded_still_extracts(tmp_path: Path):
    ts = REGISTRY["find_replace"]()
    stub = StubClient(['find_replace("teh", "the")'])  # 没有 done() 就用尽轮数
    r = run_toolset(
        stub, _Task("teh fox"), ts, Budget(max_turns=1), "INSTR", tmp_path / "e"
    )
    assert r.status == "budget_exceeded"
    assert r.output == "the fox"  # extract 仍执行


def test_find_replace_replace_all_and_not_found(tmp_path: Path):
    ts = REGISTRY["find_replace"]()
    stub = StubClient(
        ['find_replace("zzz", "q")', 'find_replace("teh", "the")', "done()"]
    )
    r = run_toolset(
        stub, _Task("teh teh fox"), ts, Budget(max_turns=5), "INSTR", tmp_path / "f"
    )
    assert r.status == "done"
    assert r.output == "the the fox"  # replace-all
    assert "PATTERN_NOT_FOUND" in stub.calls[1][-1].content


def test_rewrite_pieces_splits_units(tmp_path: Path):
    ts = REGISTRY["rewrite_pieces"]()
    meta = {"unit_boundaries": [0, 5]}
    stub = StubClient(
        ['{"ocr_postcorrection_output": "AAAA"}', '{"ocr_postcorrection_output": "BBBB"}']
    )
    r = run_toolset(
        stub, _Task("aaaa\nbbbb", meta), ts, Budget(max_turns=1), "INSTR", tmp_path / "g"
    )
    assert r.status == "done"
    assert r.output == "AAAA\nBBBB"
    assert len(r.turns) == 2


def test_determinism_same_stub_twice(tmp_path: Path):
    def once(d: Path):
        ts = REGISTRY["patch"]()
        stub = StubClient(['replace(b1, "teh", "the")', "done()"])
        return run_toolset(stub, _Task("teh x"), ts, Budget(max_turns=4), "I", d)

    r1 = once(tmp_path / "h1")
    r2 = once(tmp_path / "h2")
    assert (r1.output, r1.status, len(r1.turns)) == (r2.output, r2.status, len(r2.turns))
