"""测试 2：上下文组装（tool + BLOCR system 提示词 + smoke dataset 首条 user 输入）。

组装口径（09「Loop」规则 1）：
    messages[0] = system: instruction（BLOCR SYSTEM_PROMPT 副本）+ prompt_clause
    messages[1] = user:   输入呈现（present_input + format_input）

- stub 变体：构造的 smoke dataset × patch 工具集，StubClient 捕获首轮请求逐字校验。
- live 变体：把组装好的完整 patch 首回合上下文真发一次并计时——
  与 test_llm_live 的极小请求对照，用于定位「实验卡死」在端点/模型还是装配层。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm import StubClient
from toolsets import REGISTRY, Budget, run_toolset
from toolsets.core import build_initial_messages, format_input

ROOT = Path(__file__).resolve().parents[1]
BLOCR_INSTRUCTION = (
    ROOT / "datasets" / "hipe_2026" / "instruction.md"
).read_text(encoding="utf-8")


def _smoke_dataset() -> SimpleNamespace:
    """构建的 smoke dataset：一条短 OCR 样本 + BLOCR 指令。"""
    task = SimpleNamespace(
        task_id="smoke/1",
        input="Tbe quick brown fox jumPs over the l4zy dog.",
        reference="The quick brown fox jumps over the lazy dog.",
        meta={"language": "en"},
    )
    return SimpleNamespace(tasks=[task], instruction=BLOCR_INSTRUCTION)


def test_assembly_patch_first_turn(tmp_path: Path):
    ds = _smoke_dataset()
    toolset = REGISTRY["patch"]()
    stub = StubClient(["done()"])
    result = run_toolset(
        stub, ds.tasks[0], toolset, Budget(max_turns=1), ds.instruction, tmp_path
    )
    assert result.status == "done"

    request = stub.calls[0]
    assert [m.role for m in request] == ["system", "user"]

    # system = BLOCR 指令 + 工具条款（逐字、顺序固定）
    assert request[0].content == ds.instruction + "\n\n" + toolset.prompt_clause
    assert request[0].content.startswith(ds.instruction)

    # user = 输入呈现（patch = 标注视图；含围栏与原文内容）
    ctx = toolset.make_context(ds.tasks[0].input, ds.tasks[0].meta, tmp_path / "ctx")
    expected_user = format_input(
        toolset.present_input(ds.tasks[0].input, ctx), ds.tasks[0].meta
    )
    assert request[1].content == expected_user
    assert "jumPs" in request[1].content  # OCR 原文内容在 user 里
    assert ds.instruction not in request[1].content  # 指令不混入 user


def test_assembly_shared_across_runners(tmp_path: Path):
    """loop 与 rewrite_pieces 自定义 runner 共用同一组装函数。"""
    ds = _smoke_dataset()
    pieces = REGISTRY["rewrite_pieces"]()
    stub = StubClient(['{"ocr_postcorrection_output": "x"}'])
    run_toolset(stub, ds.tasks[0], pieces, Budget(max_turns=1), ds.instruction, tmp_path)
    expected = build_initial_messages(
        ds.instruction, pieces.prompt_clause, ds.tasks[0].input, ds.tasks[0].meta
    )
    assert [(m.role, m.content) for m in stub.calls[0]] == [
        (m.role, m.content) for m in expected
    ]


def _first_hipe_chunk() -> SimpleNamespace:
    """icdar2017 dev en 目标文章的首个 chunk（不打 experiment 装配层）。"""
    data = (
        ROOT / "related_source" / "HIPE-OCRepair-2026-data-0.9.5" / "data"
        / "v0.9" / "icdar2017" / "en"
    )
    path = next(data.glob("*_dev_*.jsonl"))
    with path.open(encoding="utf-8") as f:
        row = json.loads(next(f))
    return SimpleNamespace(
        input=row["ocr_hypothesis"]["transcription_unit"],
        meta={"language": "en"},
    )


@pytest.mark.live
def test_live_patch_first_turn_timing(tmp_path: Path):
    """live：真实发送组装好的 patch 首回合上下文（目标文章首 chunk），计时定位。"""
    from llm import CredentialError, build_client, load_env_file, load_model_config

    load_env_file()
    try:
        client = build_client(load_model_config("glm-5.3-flash"))
    except CredentialError:
        pytest.skip("VOLCENGINE_API_KEY 未配置")

    toolset = REGISTRY["patch"]()
    task = _first_hipe_chunk()
    ctx = toolset.make_context(task.input, task.meta, tmp_path)
    messages = build_initial_messages(
        BLOCR_INSTRUCTION,
        toolset.prompt_clause,
        toolset.present_input(task.input, ctx),
        task.meta,
    )
    total_chars = sum(len(m.content) for m in messages)
    deltas: list[str] = []
    t0 = time.monotonic()
    completion = client.complete(messages, on_delta=deltas.append)
    elapsed = time.monotonic() - t0
    print(
        f"\n[live] patch 首回合: prompt={total_chars} chars, "
        f"{elapsed:.1f}s, out={len(completion.text or '')} chars, "
        f"deltas={len(deltas)}, usage={completion.usage}"
    )
    assert completion.text is not None
    assert deltas, "流式无增量（活动不可观测）"
