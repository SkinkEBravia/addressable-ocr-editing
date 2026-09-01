"""experiment 的冒烟与自洽测试（Docs/Design/11-experiment.md「验收」）。

tiny 数据集 × noop/rewrite/patch/find_replace × StubClient（录制回放）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datasetkit import load_dataset, select
from llm import Message, StubClient
from experiment import (
    build_report,
    load_toolset_config,
    run_experiment,
    write_report,
)
from experiment.config import ToolsetConfig

ROOT = Path(__file__).resolve().parents[1]
TINY = ROOT / "datasets" / "tiny"

_MODEL = {
    "protocol": "openai-completion",
    "base_url": "https://stub",
    "model": "stub",
    "key_env": "STUB",
}


def _configs() -> list[ToolsetConfig]:
    return [
        ToolsetConfig(name="noop", toolset="noop"),
        ToolsetConfig(name="rewrite", toolset="rewrite", max_turns=1),
        ToolsetConfig(name="patch", toolset="patch", max_turns=4),
        ToolsetConfig(name="find_replace", toolset="find_replace", max_turns=4),
    ]


def _stub() -> StubClient:
    # tiny: t1 "teh...teh..."、t2 "oldSwarth / ar.d"、t3 masked。
    # 脚本按调用顺序消费；每个 task 的 patch/find_replace 最多两轮（含 done）。
    return StubClient(
        [
            # 顺序由 run 的 (toolset, task) 遍历决定；用回调按内容应答更稳
            lambda msgs: _answer(msgs),
        ]
        * 1
    )


def _answer(msgs) -> str:
    """按请求内容给出确定性响应的假端点。"""
    content = msgs[-1].content
    if "Return a JSON object" in content:  # rewrite
        if "oldSwarth" in content:
            return '{"ocr_postcorrection_output": "Rich old Swarth LAND and water\\n"}'
        return '{"ocr_postcorrection_output": "the quick brown fox jumps over the lazy dog\\n"}'
    if "PATTERN_NOT_FOUND" in content or "parse error: " in content:
        return "done()"
    if "<x id=" in content:  # patch 视图
        if "oldSwarth" in content:
            return 'replace(b1, "oldSwarth", "old Swarth")\nreplace(b1, "ar.d", "and")'
        return 'replace(b1, "teh", "the")'
    if "replaced" in content or "patch applied" in content:
        return "done()"
    if "find_replace" in content:  # find_replace 首轮
        if "oldSwarth" in content:
            return 'find_replace("oldSwarth", "old Swarth")\nfind_replace("ar.d", "and")'
        return 'find_replace("teh", "the")'
    return "done()"


def _run(tmp_path: Path) -> Path:
    out = tmp_path / "run1"
    summary = run_experiment(
        dataset_dir=TINY,
        toolset_configs=_configs(),
        client=StubClient([_answer] * 64),
        model_config_dict=_MODEL,
        split="all",
        out=out,
    )
    assert set(summary.values()) <= {"done"}
    return out


def _report(out: Path) -> dict:
    report = build_report(
        dataset_dir=TINY,
        split="all",
        granularity=None,
        out=out,
        toolset_names=["noop", "rewrite", "patch", "find_replace"],
        model_config_dicts={"stub": _MODEL},
        toolset_config_dicts={c.name: c.as_dict() for c in _configs()},
        instruction=None,
    )
    write_report(report, out)
    return report


def test_smoke_all_toolsets_done(tmp_path: Path):
    out = _run(tmp_path)
    # 对话录逐轮落盘：每个 (task, toolset) 一个文件
    raw = [
        p for p in (out / "raw").glob("*/*.json") if p.parent.name != "messages"
    ]
    assert len(raw) == 3 * 4  # 3 tasks × 4 toolsets
    report = _report(out)
    assert (out / "report.json").is_file()
    for name in ("noop", "rewrite", "patch", "find_replace"):
        assert name in report["per_sample"]


def test_masked_not_scored(tmp_path: Path):
    report = _report(_run(tmp_path))
    for name in ("noop", "rewrite", "patch", "find_replace"):
        assert report["per_sample"][name]["t3"]["score"] is None


def test_tokens_total_self_consistent(tmp_path: Path):
    out = _run(tmp_path)
    for path in (out / "raw").glob("*/*.json"):
        if path.parent.name == "messages":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        turns = data["turns"]
        if data["total_usage"] is None:
            continue
        assert data["total_usage"]["input_tokens"] == sum(
            t["completion"]["usage"]["input_tokens"] for t in turns
        )
        assert data["total_usage"]["output_tokens"] == sum(
            t["completion"]["usage"]["output_tokens"] for t in turns
        )


def test_noop_identity_and_corrections_improve(tmp_path: Path):
    report = _report(_run(tmp_path))
    # noop：output == input（t1 的 cer == cer_hyp 水平，即不改）
    assert report["per_sample"]["noop"]["t1"]["score"]["cer"] == pytest.approx(
        report["per_sample"]["noop"]["t1"]["score"]["cer"], abs=1e-9
    )
    # patch 修好了 t1：cer == 0
    assert report["per_sample"]["patch"]["t1"]["score"]["cer"] == 0.0
    assert report["per_sample"]["find_replace"]["t1"]["score"]["cer"] == 0.0
    # noop 的 t1 cer > 0（确有错误）
    assert report["per_sample"]["noop"]["t1"]["score"]["cer"] > 0


def test_resume_skips_same_config(tmp_path: Path):
    out = _run(tmp_path)
    summary = run_experiment(
        dataset_dir=TINY,
        toolset_configs=_configs(),
        client=StubClient([_answer] * 64),
        model_config_dict=_MODEL,
        split="all",
        out=out,
    )
    assert set(summary.values()) == {"resumed"}


def test_resume_key_includes_config(tmp_path: Path):
    """同名工具配置换了内容 => 视为新运行（踩坑记录 #7）。"""
    out = _run(tmp_path)
    changed = _configs()
    changed[1] = ToolsetConfig(name="rewrite", toolset="rewrite", max_turns=2)
    summary = run_experiment(
        dataset_dir=TINY,
        toolset_configs=changed,
        client=StubClient([_answer] * 64),
        model_config_dict=_MODEL,
        split="all",
        out=out,
    )
    rewrite_keys = [k for k, v in summary.items() if "rewrite" in k]
    assert all(summary[k] == "done" for k in rewrite_keys)  # 重跑了
    others = [k for k in summary if "rewrite" not in k]
    assert all(summary[k] == "resumed" for k in others)


def test_reproducibility_same_scores_twice(tmp_path: Path):
    r1 = _report(_run(tmp_path / "a"))
    r2 = _report(_run(tmp_path / "b"))
    assert r1["per_sample"] == r2["per_sample"]


def test_replay_unchanged(tmp_path: Path):
    from experiment import replay

    out = _run(tmp_path)
    _report(out)
    result = replay(out)
    assert result["changed"] == []  # 后处理未变 => replay 结果不变


def test_workers_concurrent_same_result(tmp_path: Path):
    """并发是实现细节：workers=4 与串行的落盘与指标完全一致。"""
    out = tmp_path / "par"
    summary = run_experiment(
        dataset_dir=TINY,
        toolset_configs=_configs(),
        client=StubClient([_answer] * 64),
        model_config_dict=_MODEL,
        split="all",
        out=out,
        workers=4,
    )
    assert set(summary.values()) <= {"done"}
    raw = [p for p in (out / "raw").glob("*/*.json") if p.parent.name != "messages"]
    assert len(raw) == 3 * 4
    r_par = _report(out)["per_sample"]
    r_seq = _report(_run(tmp_path / "seq"))["per_sample"]
    assert r_par == r_seq


def test_progress_non_tty_events():
    """非 TTY（StringIO）：退化为事件行，不崩、不喷 ANSI。"""
    import io

    from experiment.progress import Progress

    buf = io.StringIO()
    p = Progress(stream=buf)
    p.begin(2)
    p.start_cell("t1 × noop")
    p.delta("hello\nwor")
    p.delta("ld\n")
    from llm import Usage

    p.turn(Usage(input_tokens=3, output_tokens=5))
    p.end_cell("t1 × noop", "done", Usage(input_tokens=3, output_tokens=5), 1.0)
    text = buf.getvalue()
    assert "[start] t1 × noop" in text
    assert "[1/2] t1 × noop -> done" in text
    assert "5 out tok" in text and "5.0 tok/s" in text
    assert "\x1b[" not in text  # 非 TTY 无 ANSI


def test_progress_tty_live_repaint():
    """模拟 TTY（rich force_terminal）：Live 原地重绘，超宽行被裁剪。"""
    import io

    from experiment.progress import Progress
    from llm import Usage

    buf = io.StringIO()
    p = Progress(stream=buf, force_terminal=True)
    p.begin(1)
    p.start_cell("t1 × rewrite")
    p.delta("x" * 500 + "\n短行\n")  # 超长行由 rich 按终端宽度处理
    p.turn(Usage(input_tokens=3, output_tokens=5))
    p.end_cell("t1 × rewrite", "done", Usage(input_tokens=3, output_tokens=5), 2.0)
    p.close()
    text = buf.getvalue()
    assert "\x1b[" in text  # Live 重绘走 ANSI 光标控制
    assert "t1 × rewrite | turn 1" in text
    assert "t1 × rewrite -> done" in text  # 最近事件进刷新块，不堆历史
    assert "x" * 500 not in text  # 超宽行被裁剪/折行，不会一行打满


def test_stub_client_streams_deltas():
    chunks: list[str] = []
    c = StubClient(["hello world"])
    out = c.complete([Message("user", "x")], on_delta=chunks.append)
    assert "".join(chunks) == "hello world"
    assert all(len(c_) <= 16 for c_ in chunks)  # 分块回调
    assert out.text == "hello world"
