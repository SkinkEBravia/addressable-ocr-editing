"""experiment：冒烟 / resume / replay / 报告自洽（Docs/Design/11-experiment.md「验收」）。

全部用 StubClient 离线运行；patch cell 走真实 IR 链路。
"""

from __future__ import annotations

import json
from pathlib import Path

from agent import load_toolset_config
from experiment import SessionStore, run_experiment
from experiment.replay import replay
from experiment.report import build_report, write_report
from llm import Failure, LLMError, StubClient

TINY = Path("datasets/tiny")
REWRITE_RESP = '{"ocr_postcorrection_output": "fixed text"}'
TOOLSETS = ["noop", "rewrite", "patch"]


def _run(out: Path, script: list) -> dict:
    return run_experiment(
        dataset_dir=TINY,
        toolset_configs=[load_toolset_config(n) for n in TOOLSETS],
        client=StubClient(script),
        model_config_dict={"model": "stub"},
        split="all",
        out=out,
        workers=1,
        stream=False,
    )


def _smoke_script() -> list:
    # cell 顺序：noop(t1..t3 无调用) -> rewrite t1..t3 -> patch t1..t3
    return [REWRITE_RESP] * 3 + ["done()"] * 3


def _report(out: Path) -> dict:
    report = build_report(
        dataset_dir=TINY,
        split="all",
        out=out,
        toolset_names=TOOLSETS,
        model_config_dicts={"stub": {"model": "stub"}},
        toolset_config_dicts={n: load_toolset_config(n).as_dict() for n in TOOLSETS},
        instruction=None,
    )
    write_report(report, out)
    return report


def test_smoke_and_report_consistency(tmp_path):
    out = tmp_path / "run"
    summary = _run(out, _smoke_script())
    assert set(summary.values()) == {"done"}

    report = _report(out)
    store = SessionStore(out)
    for name in TOOLSETS:
        rows = report["per_sample"][name]
        assert set(rows) == {"t1", "t2", "t3"}
        for task_id, row in rows.items():
            assert row["status"] == "done"
            # tokens_total == Σ 各轮 usage（端点计数自洽）
            session = store.read(task_id, name)
            assert session is not None
            usage = session.usage
            assert usage is not None
            assert row["usage"]["tokens_total"] == usage.total
        # masked 样本不出数
        assert rows["t3"]["score"] is None
    assert report["per_sample"]["rewrite"]["t1"]["score"]["cer"] is not None
    # noop 锚点：output == input，指标即 no-correction 基线
    t1 = report["per_sample"]["noop"]["t1"]
    assert t1["usage"]["tokens_total"] == 0


def test_resume_skips_done_and_reruns_failed(tmp_path):
    out = tmp_path / "run"
    _run(out, _smoke_script())

    # 第二遍：全部 resumed，stub 零调用
    summary = _run(out, [])
    assert set(summary.values()) == {"resumed"}

    # 把一个 rewrite cell 标记为 failed ⇒ 只重跑它（1 次调用）
    tape = out / "sessions" / "t2" / "rewrite.json"
    data = json.loads(tape.read_text(encoding="utf-8"))
    data["status"] = "failed:rejected"
    tape.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    summary = _run(out, [REWRITE_RESP])
    statuses = list(summary.values())
    assert statuses.count("resumed") == 8
    assert statuses.count("done") == 1
    assert summary[str(("t2", "rewrite"))] == "done"

    # 中断残留（running）同样重跑
    data = json.loads(tape.read_text(encoding="utf-8"))
    data["status"] = "running"
    tape.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = _run(out, [REWRITE_RESP])
    assert summary[str(("t2", "rewrite"))] == "done"


def test_failed_cell_carries_failure_detail(tmp_path):
    out = tmp_path / "run"
    failure = Failure(
        stage="llm", kind="rejected", message="HTTP 400", http_status=400, attempts=1,
        detail={"body_excerpt": "bad request"},
    )
    script = [LLMError(failure)] + [REWRITE_RESP] * 2 + ["done()"] * 3
    summary = _run(out, script)
    assert summary[str(("t1", "rewrite"))] == "failed:rejected"

    report = _report(out)
    row = report["per_sample"]["rewrite"]["t1"]
    assert row["status"] == "failed:rejected"
    assert row["failure"]["kind"] == "rejected"
    assert row["failure"]["http_status"] == 400
    assert row["failure"]["detail"]["body_excerpt"] == "bad request"
    # 回退原文仍评分；失败按 kind 聚合
    assert row["score"] is not None
    assert report["aggregate"]["rewrite"]["failures"] == {"rejected": 1}


def test_replay_is_deterministic_noop(tmp_path):
    out = tmp_path / "run"
    _run(out, _smoke_script())
    _report(out)
    result = replay(out)
    assert result == {"changed": [], "lower_bound": []}


def test_replay_picks_up_extract_change(tmp_path, monkeypatch):
    """后处理变了（extract 改了）⇒ replay 产出变化并记入 changed，不调 API。"""
    out = tmp_path / "run"
    _run(out, _smoke_script())
    _report(out)

    import agent.standard as std

    monkeypatch.setattr(std, "extract_rewrite_text", lambda text: "postprocessed")
    result = replay(out)
    assert sorted(result["changed"]) == [
        "t1 × rewrite",
        "t2 × rewrite",
        "t3 × rewrite",
    ]
    session = SessionStore(out).read("t1", "rewrite")
    assert session is not None and session.output == "postprocessed"


def test_resumable_accepts_legacy_hash(tmp_path):
    """过渡兼容：旧配方（绝对路径 dataset_dir）算出的磁带哈希仍可 resume。"""
    from agent import Budget, Session
    from experiment import SessionStore

    store = SessionStore(tmp_path / "out")
    s = Session(task_id="t1", toolset="noop", config_hash="legacy-hash",
                budget=Budget(), status="done", output="x")
    store.write(s)
    assert store.resumable("t1", "noop", "legacy-hash") is not None
    assert store.resumable("t1", "noop", "new-hash") is None
    assert store.resumable("t1", "noop", "new-hash", legacy="legacy-hash") is not None


def test_cli_noop_needs_no_credentials(tmp_path):
    """纯 noop 运行不需要任何凭证（不建 client、不发请求）。"""
    cfg = tmp_path / "m.toml"
    cfg.write_text(
        'protocol = "openai-response"\nbase_url = "http://x"\n'
        'model = "m"\nkey_env = "DEFINITELY_MISSING_KEY_XYZ"\n',
        encoding="utf-8",
    )
    from experiment.__main__ import main

    rc = main([
        "--dataset", "datasets/tiny", "--toolsets", "noop",
        "--model", str(cfg), "--split", "all",
        "--out", str(tmp_path / "out"), "--reporter", "null",
    ])
    assert rc == 0
    assert (tmp_path / "out" / "report.json").is_file()


def test_cli_rejects_empty_toolsets_before_creating_run(tmp_path, capsys):
    from experiment.__main__ import main

    out = tmp_path / "out"
    rc = main([
        "--dataset", "datasets/tiny", "--toolsets", "",
        "--model", "unused", "--split", "all",
        "--out", str(out), "--reporter", "null",
    ])

    assert rc == 2
    assert "--toolsets must contain at least one toolset name" in capsys.readouterr().err
    assert not out.exists()
