"""agent：Session / loop / 三通道错误（Docs/Design/09-tools.md「验收」）。"""

from __future__ import annotations

import pytest

from pathlib import Path

from agent import (
    Budget,
    Session,
    ToolCall,
    ToolParseError,
    ToolResult,
    build_initial_messages,
    run_session,
    start_session,
)
from agent.standard import FindReplaceToolSet, NoopToolSet, RewriteToolSet
from llm import Failure, LLMError, StubClient
from sourceio import SourceText

TASK_INPUT = "hello wrld"
INST = "You correct OCR errors."


def run_one(toolset, script, tmp_path: Path, *, budget: Budget | None = None):
    client = StubClient(script)
    session, messages = start_session(
        toolset,
        label=toolset.name,
        task_id="t1",
        task_input=TASK_INPUT,
        task_meta={"language": "en"},
        instruction=INST,
        workdir=tmp_path / "work",
        config_hash="h",
        budget=budget or Budget(),
    )
    run_session(client, toolset, session, messages, fallback_text=TASK_INPUT)
    return session, client


def test_build_initial_messages(tmp_path):
    msgs = build_initial_messages(INST, "CLAUSE", "presented", {"language": "en"})
    assert msgs[0].role == "system"
    assert msgs[0].content == INST + "\n\nCLAUSE"
    assert msgs[1].role == "user"
    assert "--- INPUT (language: en) ---\npresented\n--- END OF INPUT ---" == msgs[1].content


def test_noop_zero_turns(tmp_path):
    session, client = run_one(NoopToolSet(), [], tmp_path)
    assert session.status == "done"
    assert session.turns == []
    assert session.output == TASK_INPUT
    assert client.calls == []  # 不调 LLM


def test_rewrite_single_turn(tmp_path):
    session, _ = run_one(
        RewriteToolSet(), ['{"ocr_postcorrection_output": "fixed"}'], tmp_path
    )
    assert session.status == "done"
    assert len(session.turns) == 1
    assert session.output == "fixed"
    assert session.usage is not None and session.usage.output_tokens > 0


def test_parse_error_goes_to_dialogue(tmp_path):
    session, client = run_one(
        FindReplaceToolSet(), ["not a call", "done()"], tmp_path,
        budget=Budget(max_turns=4),
    )
    assert session.status == "done"
    assert session.turns[0].parse_error is not None
    # 第二轮请求里带着 parse error 反馈（对话通道，无独立重试）
    second_request = client.calls[1]
    assert any("parse error" in m.content for m in second_request if m.role == "user")


def test_llm_error_failure_channel(tmp_path):
    failure = Failure(stage="llm", kind="incomplete", message="no output text",
                      attempts=1)
    session, _ = run_one(RewriteToolSet(), [LLMError(failure)], tmp_path)
    assert session.status == "failed:incomplete"
    assert session.failure is not None
    assert session.failure.kind == "incomplete"
    assert session.turns == []  # turn-0 失败：failure 挂在 Session 上
    assert session.output == TASK_INPUT  # 回退原文


def test_tool_exception_is_failure_not_feedback(tmp_path):
    class BoomToolSet:
        name = "boom"
        uses_llm = True
        prompt_clause = ""

        def make_tool_state(self, task_input, task_meta, workdir):
            return {}

        def present_input(self, task_input, tool_state):
            return task_input

        def parse(self, text):
            return (ToolCall("explode"),)

        def invoke(self, call, tool_state):
            raise RuntimeError("boom")

        def extract(self, tool_state, session):
            return SourceText(text="x", encoding="utf-8", bom=b"")

    session, _ = run_one(BoomToolSet(), ["explode()"], tmp_path)
    assert session.status == "failed:tool_error"
    assert session.failure is not None
    assert session.failure.stage == "tool"
    assert "boom" in session.failure.message
    assert "traceback" in session.failure.detail
    assert session.output == TASK_INPUT


def test_budget_exceeded_still_extracts(tmp_path):
    session, _ = run_one(
        FindReplaceToolSet(),
        ['find_replace("wrld", "world")'],
        tmp_path,
        budget=Budget(max_turns=1),
    )
    assert session.status == "budget_exceeded"
    assert session.output == "hello world"  # fold 已生效，extract 照常


def test_find_replace_multi_turn_fold(tmp_path):
    session, _ = run_one(
        FindReplaceToolSet(),
        ['find_replace("wrld", "world")', "done()"],
        tmp_path,
        budget=Budget(max_turns=4),
    )
    assert session.status == "done"
    assert session.output == "hello world"
    assert session.turns[0].results[0].ok


def test_tool_init_failure(tmp_path):
    class InitBoom(RewriteToolSet):
        name = "init_boom"

        def make_tool_state(self, task_input, task_meta, workdir):
            raise OSError("disk full")

    session, client = run_one(InitBoom(), [], tmp_path)
    assert session.status == "failed:tool_init"
    assert session.failure is not None and session.failure.stage == "tool"
    assert client.calls == []  # 没发请求


# ---------------------------------------------------------------- 顺序修复工具集

SEQ_INPUT = "aa\nbb\ncc"
SEQ_META = {"language": "en", "unit_boundaries": [0, 3, 6]}


def run_seq(toolset, script, tmp_path):
    from agent.sequential import PatchSeqToolSet, RewriteSeqToolSet  # noqa: F401

    client = StubClient(script)
    session, messages = start_session(
        toolset,
        label=toolset.name,
        task_id="doc1",
        task_input=SEQ_INPUT,
        task_meta=SEQ_META,
        instruction=INST,
        workdir=tmp_path / "work",
        config_hash="h",
        budget=Budget(max_turns=64),
    )
    run_session(client, toolset, session, messages, fallback_text=SEQ_INPUT)
    return session, client


def test_rewrite_seq_one_turn_per_chunk(tmp_path):
    from agent.sequential import RewriteSeqToolSet

    session, client = run_one = run_seq(
        RewriteSeqToolSet(),
        ['{"ocr_postcorrection_output": "AA"}',
         '{"ocr_postcorrection_output": "BB"}',
         '{"ocr_postcorrection_output": "CC"}'],
        tmp_path,
    )
    assert session.status == "done"  # finish 终止，不是 budget_exceeded
    assert len(session.turns) == 3  # 轮数 == chunk 数
    assert session.output == "AA\nBB\nCC"
    # 无反馈口径：第二轮请求里只有下一个 chunk 的呈现，无 error 字样
    second = client.calls[1]
    assert second[-1].role == "user"
    assert "bb" in second[-1].content and "error" not in second[-1].content


def test_patch_seq_applies_per_chunk(tmp_path):
    from agent.sequential import PatchSeqToolSet

    session, client = run_seq(
        PatchSeqToolSet(apply_mode="best_effort"),
        ['replace(b1, "aa", "AA")',
         'replace(b1, "bb", "BB")',
         'replace(b1, "cc", "CC")'],
        tmp_path,
    )
    assert session.status == "done"
    assert len(session.turns) == 3
    assert session.output == "AA\nBB\nCC"
    # 每个 chunk 独立 IR 会话：第二轮请求呈现的是下一个 chunk 的标注视图
    second = client.calls[1]
    assert "bb" in second[-1].content and "error" not in second[-1].content


def test_patch_seq_bad_patch_keeps_chunk_silently(tmp_path):
    from agent.sequential import PatchSeqToolSet

    session, client = run_seq(
        PatchSeqToolSet(apply_mode="best_effort"),
        ['replace(b1, "aa", "AA")',
         "garbage, not a patch",  # 方言错误：该 chunk 保留原文，不回灌错误
         'replace(b1, "cc", "CC")'],
        tmp_path,
    )
    assert session.status == "done"
    assert session.output == "AA\nbb\nCC"
    third = client.calls[2]
    assert "error" not in third[-1].content  # 模型从未看到错误信息


# ---------------------------------------------------------------- swe_edit 行号锚


def test_swe_edit_line_range_replace(tmp_path):
    from agent.swe_edit import SweEditToolSet

    ts = SweEditToolSet()
    # done() 必须单独成消息：先 edit 后 done 两轮
    client = StubClient(['edit(2, 2, "BB")', "done()"])
    session, messages = start_session(
        ts,
        label="swe_edit",
        task_id="t1",
        task_input="aa\nbb\ncc",
        task_meta={},
        instruction=INST,
        workdir=tmp_path / "work",
        config_hash="h",
        budget=Budget(max_turns=4),
    )
    run_session(client, ts, session, messages, fallback_text="aa\nbb\ncc")
    assert session.status == "done"
    assert session.output == "aa\nBB\ncc"
    # 首轮请求呈现带行号的视图
    first = client.calls[0]
    assert any("2: bb" in m.content for m in first)


def test_swe_edit_multiline_and_out_of_range(tmp_path):
    import json as _json

    from agent.swe_edit import SweEditToolSet

    ts = SweEditToolSet()
    client = StubClient([
        "edit(2, 3, " + _json.dumps("B1\nB2") + ")",  # 2 行换成 2 行
        'edit(9, 10, "x")',  # 越界 -> 对话通道报错
        "done()",
    ])
    session, messages = start_session(
        ts, label="swe_edit", task_id="t1", task_input="aa\nbb\ncc",
        task_meta={}, instruction=INST, workdir=tmp_path / "work",
        config_hash="h", budget=Budget(max_turns=4),
    )
    run_session(client, ts, session, messages, fallback_text="aa\nbb\ncc")
    assert session.status == "done"
    assert session.output == "aa\nB1\nB2"
    # 越界错误走了对话通道（模型看得到），不是失败通道
    assert session.turns[1].results[0].ok is False
    assert "out of range" in session.turns[1].results[0].feedback


# ---------------------------------------------------------------- swe_bash 环境

import json as _json_mod
import shutil as _shutil

import pytest as _pytest

_HAS_BASH = _shutil.which("bash") is not None


@_pytest.mark.skipif(not _HAS_BASH, reason="需要 Git Bash")
def test_swe_bash_edit_script_roundtrip(tmp_path):
    from agent.swe_bash import SweBashToolSet

    ts = SweBashToolSet()
    script = [
        "bash(" + _json_mod.dumps("edit 2:2 << end_of_edit\nBB\nend_of_edit") + ")",
        "done()",
    ]
    session, messages = start_session(
        ts, label="swe_bash", task_id="t1", task_input="aa\nbb\ncc",
        task_meta={}, instruction=INST, workdir=tmp_path / "work",
        config_hash="h", budget=Budget(max_turns=4),
    )
    run_session(StubClient(script), ts, session, messages, fallback_text="aa\nbb\ncc")
    assert session.status == "done"
    assert session.output == "aa\nBB\ncc"
    assert session.turns[0].results[0].ok is True


@_pytest.mark.skipif(not _HAS_BASH, reason="需要 Git Bash")
def test_swe_bash_env_scrubbed_and_bash_available(tmp_path):
    from agent.swe_bash import SweBashToolSet

    ts = SweBashToolSet()
    state = ts.make_tool_state("aa\nbb\ncc", {}, tmp_path / "work")
    assert (state["workdir"] / "text.txt").is_file()
    assert (state["workdir"] / "bin" / "edit").is_file()
    # 密钥类变量不进子进程环境
    assert not any("KEY" in k or "TOKEN" in k or "SECRET" in k for k in state["env"])
    code, out = ts._backend.run("cat -n text.txt", cwd=state["workdir"],
                                env=state["env"], timeout=30)
    assert code == 0 and "2\tbb" in out or "2:bb" in out or "bb" in out


@_pytest.mark.skipif(not _HAS_BASH, reason="需要 Git Bash")
def test_swe_bash_replace_script(tmp_path):
    from agent.swe_bash import SweBashToolSet

    ts = SweBashToolSet()
    state = ts.make_tool_state("aa\nbb\ncc", {}, tmp_path / "work")
    assert (state["workdir"] / "bin" / "replace").is_file()
    code, out = ts._backend.run(
        "replace bb BB", cwd=state["workdir"], env=state["env"], timeout=30
    )
    assert code == 0 and "replaced 1" in out
    assert (state["workdir"] / "text.txt").read_text(encoding="utf-8") == "aa\nBB\ncc"
    code2, out2 = ts._backend.run(
        "replace zz Z", cwd=state["workdir"], env=state["env"], timeout=30
    )
    assert code2 != 0 and "PATTERN_NOT_FOUND" in out2


# ---------------------------------------------------------------- 末尾 done 标记


def test_trailing_done_executes_calls_then_finishes(tmp_path):
    """done() 在最后一行：前面的调用照常执行，然后 done 收束（一轮完成）。"""
    session, client = run_one(
        FindReplaceToolSet(),
        ['find_replace("wrld", "world")\ndone()'],
        tmp_path,
        budget=Budget(max_turns=4),
    )
    assert session.status == "done"
    assert len(session.turns) == 1
    assert session.output == "hello world"
    assert session.turns[0].results[-1].feedback == ""
    assert session.turns[0].results[-1].ok is True


def test_trailing_done_bare_form(tmp_path):
    """bare `done`（无括号）在最后一行同样算完成。"""
    session, _ = run_one(
        FindReplaceToolSet(),
        ['find_replace("wrld", "world")\ndone'],
        tmp_path,
        budget=Budget(max_turns=4),
    )
    assert session.status == "done"
    assert session.output == "hello world"


def test_done_in_middle_still_parse_error(tmp_path):
    """done() 出现在中间仍是方言错误（对话通道）。"""
    session, _ = run_one(
        FindReplaceToolSet(),
        ['done()\nfind_replace("wrld", "world")', "done()"],
        tmp_path,
        budget=Budget(max_turns=4),
    )
    assert session.turns[0].parse_error is not None
    assert session.status == "done"
    assert session.output == TASK_INPUT  # 替换在作废的第 0 轮里，未生效


def test_patch_trailing_done(tmp_path):
    from agent.patch import PatchToolSet

    ts = PatchToolSet()
    client = StubClient(['replace(b1, "wrld", "world")\ndone()'])
    session, messages = start_session(
        ts, label="patch", task_id="t1", task_input=TASK_INPUT,
        task_meta={}, instruction=INST, workdir=tmp_path / "work",
        config_hash="h", budget=Budget(max_turns=4),
    )
    run_session(client, ts, session, messages, fallback_text=TASK_INPUT)
    assert session.status == "done"
    assert session.output == "hello world"
    assert len(session.turns) == 1


# --- allowed_ops：parse 层强制的操作白名单 ---


def test_patch_replace_rejects_disallowed_ops_at_parse():
    """白名单外的操作在 parse 层被拒，错误经对话通道回给模型。"""
    from agent.patch import PatchToolSet
    from agent.toolset import ToolParseError

    ts = PatchToolSet(allowed_ops=frozenset({"replace"}))
    with pytest.raises(ToolParseError) as exc:
        ts.parse('append(b1, "new block")')
    assert "append" in str(exc.value)
    assert "replace" in str(exc.value)


def test_patch_replace_accepts_allowed_ops():
    from agent.patch import PatchToolSet

    ts = PatchToolSet(allowed_ops=frozenset({"replace"}))
    calls = ts.parse('replace(b1, "teh", "the")')
    assert [c.name for c in calls] == ["run_patch"]


def test_patch_replace_hides_disallowed_ops_from_prompt():
    """提示词与拦截同源：不在白名单内的操作不出现在条款里。"""
    from agent.patch import PatchToolSet

    ts = PatchToolSet(allowed_ops=frozenset({"replace"}))
    assert "replace(id," in ts.prompt_clause
    for op in ("append(", "merge(", "move(", "remove(", "set_attrs("):
        assert op not in ts.prompt_clause


def test_bare_patch_allows_all_ops():
    """无后缀 patch = 全部七个 SurfaceOp，不做任何拦截。"""
    from agent.patch import PatchToolSet

    ts = PatchToolSet()
    for text in ('append(b1, "x")', "remove(b2)", "merge(b1, b2)", "move(b1, b2)"):
        assert ts.parse(text)  # 不抛


def test_patch_syntax_error_still_goes_through_invoke():
    """语法错误不在 parse 层报告 —— 保持既有路径（由 invoke 的 ParseError 处理）。"""
    from agent.patch import PatchToolSet

    ts = PatchToolSet(allowed_ops=frozenset({"replace"}))
    calls = ts.parse("this is not a valid fn call at all")
    assert [c.name for c in calls] == ["run_patch"]


def test_allowed_ops_validation():
    from agent.patch import PatchToolSet

    with pytest.raises(ValueError, match="未知操作"):
        PatchToolSet(allowed_ops=frozenset({"nope"}))
    with pytest.raises(ValueError, match="不能为空集"):
        PatchToolSet(allowed_ops=frozenset())


# --- 注册表命名与历史别名 ---


def test_legacy_toolset_names_alias_current_ones():
    """历史命名必须与对应的 *_local_seq 指向同一个类。"""
    from agent.config import REGISTRY

    for legacy, current in [
        ("rewrite_seq", "rewrite_local_seq"),
        ("patch_seq", "patch_local_seq"),
        ("swe_edit_seq", "swe_edit_local_seq"),
        ("find_replace_seq", "find_replace_local_seq"),
    ]:
        assert REGISTRY[legacy] is REGISTRY[current], f"{legacy} 与 {current} 不同源"


def test_toolset_registry_matches_design_doc():
    """09-tools.md 的标准工具配置表必须覆盖注册表的全部**当前**命名。

    历史别名（_LEGACY_TOOLSET_NAMES）不要求出现在表中。
    """
    from pathlib import Path

    from agent.config import _LEGACY_TOOLSET_NAMES, REGISTRY

    doc = (Path(__file__).resolve().parents[1] / "Docs/Design/09-tools.md").read_text(
        encoding="utf-8"
    )
    missing = [
        name for name in REGISTRY
        if name not in _LEGACY_TOOLSET_NAMES and f"`{name}`" not in doc
    ]
    assert not missing, f"09-tools.md 未记录: {missing}"
