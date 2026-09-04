from pathlib import Path
import pytest
from agent.sequential import (
    SweEditSeqToolSet,
    FindReplaceSeqToolSet,
    PatchGlobalSeqToolSet,
    SweEditGlobalSeqToolSet,
    FindReplaceGlobalSeqToolSet,
)
from agent.toolset import ToolCall


def test_swe_edit_seq_local(tmp_path: Path):
    """2.a: swe_edit_seq 逐 chunk 独立行号，只能修改当前 chunk."""
    ts = SweEditSeqToolSet()
    state = ts.make_tool_state("line1\nline2\nline3\nline4", {"unit_boundaries": [0, 12]}, tmp_path)
    # 第 1 轮
    p1 = ts.present_input("", state)
    assert "1: line1" in p1
    assert "2: line2" in p1
    # 编辑当前 chunk
    calls = ts.parse('edit 1:1 << end_of_edit\nnew1\nend_of_edit')
    res1 = ts.invoke(calls[0], state)
    assert not res1.finish
    # 第 2 轮呈现第二个 chunk（行号重新从 1 开始！）
    assert "1: line3" in res1.feedback
    # 编辑第二个 chunk
    calls2 = ts.parse('edit 2:2 << end_of_edit\nnew4\nend_of_edit')
    res2 = ts.invoke(calls2[0], state)
    assert res2.finish
    # 提取全文
    output = ts.extract(state, None).text
    assert output == "new1\nline2\nline3\nnew4"


def test_find_replace_seq_local(tmp_path: Path):
    """2.a: find_replace_seq 仅在当前 chunk 内生效."""
    ts = FindReplaceSeqToolSet()
    state = ts.make_tool_state("wordA foo\nwordA bar", {"unit_boundaries": [0, 10]}, tmp_path)
    # 第 1 轮替换
    calls = ts.parse('find_replace("wordA", "wordX")')
    res1 = ts.invoke(calls[0], state)
    assert not res1.finish
    # 第 2 轮不替换，直接保留
    calls2 = ts.parse('')
    res2 = ts.invoke(calls2[0], state)
    assert res2.finish
    output = ts.extract(state, None).text
    # 只有第一个 chunk 的 wordA 被改，第二个未被改
    assert output == "wordX foo\nwordA bar"


def test_patch_global_seq_retrospective(tmp_path: Path):
    """2.b: patch_global_seq 支持跨 chunk 回溯 patch."""
    ts = PatchGlobalSeqToolSet(block_size=5)
    state = ts.make_tool_state("hello world\nfoo bar", {"unit_boundaries": [0, 12]}, tmp_path)
    # 第 1 轮呈现
    p1 = ts.present_input("", state)
    assert "--- [File: chunk_0] ---" in p1
    assert "c0:b" in p1
    # 第 1 轮不改
    res1 = ts.invoke(ToolCall("run_patch", ""), state)
    assert not res1.finish
    # 第 2 轮呈现 chunk_1
    assert "--- [File: chunk_1] ---" in res1.feedback
    assert "c1:b" in res1.feedback
    # 在第 2 轮，模型回溯去修改 chunk_0 的块 c0:b1，同时修改当前 chunk_1 的块 c1:b1
    # 找到 c0:b1 对应的原文
    patch_text = 'replace("c0:b1", "hello", "HELLO")\nreplace("c1:b1", "foo", "FOO")'
    res2 = ts.invoke(ToolCall("run_patch", patch_text), state)
    assert res2.finish
    output = ts.extract(state, None).text
    assert output.startswith("HELLO")
    assert "FOO" in output


def test_swe_edit_global_seq_retrospective(tmp_path: Path):
    """2.b: swe_edit_global_seq 支持指定目标 chunk 进行回溯编辑."""
    ts = SweEditGlobalSeqToolSet()
    state = ts.make_tool_state("lineA1\nlineA2\nlineB1\nlineB2", {"unit_boundaries": [0, 14]}, tmp_path)
    # 第 1 轮不改
    res1 = ts.invoke(ts.parse('')[0], state)
    assert not res1.finish
    # 第 2 轮回溯修改 chunk_0，同时修改 chunk_1
    edit_cmds = 'edit chunk_0 1:1 << end\nMOD_A1\nend\nedit chunk_1 2:2 << end\nMOD_B2\nend'
    res2 = ts.invoke(ts.parse(edit_cmds)[0], state)
    assert res2.finish
    output = ts.extract(state, None).text
    assert output == "MOD_A1\nlineA2\nlineB1\nMOD_B2"


def test_find_replace_global_seq_retrospective(tmp_path: Path):
    """2.b: find_replace_global_seq 支持回溯替换之前呈现的 chunk."""
    ts = FindReplaceGlobalSeqToolSet()
    state = ts.make_tool_state("wordA foo\nwordB bar", {"unit_boundaries": [0, 10]}, tmp_path)
    # 第 1 轮不换
    res1 = ts.invoke(ts.parse('')[0], state)
    assert not res1.finish
    assert "--- [File: chunk_1] ---" in res1.feedback
    # 第 2 轮替换第一轮的 wordA 和当前轮的 wordB
    res2 = ts.invoke(ts.parse('find_replace("wordA", "wordX")\nfind_replace("wordB", "wordY")')[0], state)
    assert res2.finish
    output = ts.extract(state, None).text
    assert output == "wordX foo\nwordY bar"
