"""replay 的测试（对应 Docs/Design/08-eval-framework.md「重放（replay）」节）。

全部离线：先用假 client 真跑一次小实验落盘磁带，再 replay 验证。
"""

from __future__ import annotations

import json
from pathlib import Path

from experiment_app.arm_config import DEFAULT_ARMS_DIR, build_arm, load_arm_config
from experiment_app.arms import Arm
from experiment_app.datasets import Sample
from experiment_app.replay import replay_experiment
from experiment_app.report import build_report
from experiment_app.run import FakeClient, main, run_experiment
from llm import Completion, Usage


class ScriptClient:
    """可编程响应序列的假 LLMClient；usage 用确定性本地计数。"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, system: str | None = None) -> Completion:
        self.prompts.append(prompt)
        text = self._responses.pop(0)
        return Completion(
            text=text, usage=Usage(input_tokens=len(prompt), output_tokens=len(text))
        )


def make_sample(sample_id: str, ocr: str, gold: str) -> Sample:
    return Sample(
        sample_id=sample_id,
        track="unit",
        language="en",
        source_subset="toy",
        ocr_text=ocr,
        gold_text=gold,
        metadata={"document_id": sample_id, "primary_dataset_name": "toy", "language": "en"},
        unit_boundaries=(0,),
    )


def write_jsonl(path: Path, samples: tuple[Sample, ...]) -> Path:
    path.write_text(
        "".join(
            json.dumps(
                {
                    "document_metadata": s.metadata,
                    "ocr_hypothesis": {"transcription_unit": s.ocr_text},
                    "ground_truth": {"transcription_unit": s.gold_text},
                },
                ensure_ascii=False,
            )
            + "\n"
            for s in samples
        ),
        encoding="utf-8",
    )
    return path


def run_initial(
    samples: tuple[Sample, ...],
    arm_names: tuple[str, ...],
    clients: dict,
    out_dir: Path,
) -> None:
    """真跑一次小实验并落盘 report.json（模拟 main 的正常运行路径）。"""
    arms: dict[str, Arm] = {}
    configs = {}
    for name in arm_names:
        config = load_arm_config(name, DEFAULT_ARMS_DIR / f"{name}.toml")
        arms[name] = build_arm(config)
        configs[name] = config
    record = run_experiment(samples, arms, clients, out_dir)
    report = build_report(record, model="fake", arm_configs=configs)
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_results(out_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (out_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ]


# ---------------------------------------------------------------------------
# (a) 幂等：代码没变时 replay 后 corrected_text 与 report 完全一致
# ---------------------------------------------------------------------------

class TestReplayIdempotent:
    def test_replay_idempotent_via_cli(self, tmp_path: Path) -> None:
        samples = (
            make_sample("s1", "helo\nworld\n", "hello\nworld\n"),
            make_sample("s2", "ar.d so\n", "and so\n"),
        )
        data = write_jsonl(tmp_path / "dev.jsonl", samples)
        out_dir = tmp_path / "out"

        rc = main(
            ["--data", str(data), "--track", "unit", "--out", str(out_dir), "--model", "fake"],
            client_factory=lambda model, temperature=0.2: FakeClient(),
        )
        assert rc == 0
        before_results = (out_dir / "results.jsonl").read_text(encoding="utf-8")
        before_report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))

        rc = main(
            ["--data", str(data), "--track", "unit", "--out", str(out_dir), "--replay"],
        )
        assert rc == 0

        after_results = (out_dir / "results.jsonl").read_text(encoding="utf-8")
        after_report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))

        assert after_results == before_results  # 每样本每臂 corrected_text / token 全一致
        assert after_report["groups"] == before_report["groups"]
        assert after_report["paired_output_ratio"] == before_report["paired_output_ratio"]
        assert after_report["model"] == before_report["model"]
        assert after_report["arms"] == before_report["arms"]  # arms.config 保留
        assert after_report["replay"]["changed"] == 0
        assert after_report["replay"]["lower_bound"] == []


# ---------------------------------------------------------------------------
# (b) 磁带首轮坏 patch、次轮好 patch -> replay 走次轮成功
# ---------------------------------------------------------------------------

class TestReplaySecondRound:
    def test_second_round_success(self, tmp_path: Path) -> None:
        sample = make_sample("s1", "hello\nworld\n", "hello\nworld\n")
        out_dir = tmp_path / "out"
        client = ScriptClient(['remove(b99)', 'set_content(b1, "hi\\n")'])
        run_initial((sample,), ("blocr_system",), {"blocr_system": client}, out_dir)

        tape_path = out_dir / "raw" / "s1" / "blocr_system.json"
        tape = json.loads(tape_path.read_text(encoding="utf-8"))
        assert tape["rounds"] == 2
        assert tape["raw"][0]["error"]  # 首轮当时失败
        assert tape["raw"][1]["error"] is None

        result = replay_experiment((sample,), out_dir)
        record = result.run_record.records[0]
        assert record.failed is False
        assert record.corrected_text == "hi\nworld\n"  # 重放走到次轮
        assert record.rounds == 2
        assert record.tokens_in == tape["tokens_in"]  # token 沿用磁带
        assert record.tokens_out == tape["tokens_out"]
        assert result.changes == ()  # 后处理未变 -> 与磁带一致


# ---------------------------------------------------------------------------
# (c) 磁带只有失败轮 -> failed=True 回退原文
# ---------------------------------------------------------------------------

class TestReplayAllFailed:
    def test_all_failed_falls_back(self, tmp_path: Path) -> None:
        sample = make_sample("s1", "original text", "original text")
        out_dir = tmp_path / "out"
        client = ScriptClient(["bad", "bad", "bad"])  # retries=2 -> 3 轮全坏
        run_initial((sample,), ("blocr",), {"blocr": client}, out_dir)

        result = replay_experiment((sample,), out_dir)
        record = result.run_record.records[0]
        assert record.failed is True
        assert record.corrected_text == "original text"  # 回退原文
        assert record.rounds == 3
        assert result.changes == ()

    def test_lower_bound_recorded(self, tmp_path: Path) -> None:
        """磁带成功但重放失败 -> 记入 lower_bound（构造：磁带好 patch，中间塞坏轮）。"""
        sample = make_sample("s1", "hello\nworld\n", "hello\nworld\n")
        out_dir = tmp_path / "out"
        client = ScriptClient(['set_content(b1, "hi\\n")'])
        run_initial((sample,), ("blocr_system",), {"blocr_system": client}, out_dir)

        # 篡改磁带：把成功轮的 response 换成坏 patch（模拟"新代码下该轮失败"）
        tape_path = out_dir / "raw" / "s1" / "blocr_system.json"
        tape = json.loads(tape_path.read_text(encoding="utf-8"))
        tape["raw"][0]["response"] = "remove(b99)"
        tape_path.write_text(json.dumps(tape, ensure_ascii=False), encoding="utf-8")

        result = replay_experiment((sample,), out_dir)
        record = result.run_record.records[0]
        assert record.failed is True
        assert record.corrected_text == "hello\nworld\n"
        assert result.lower_bound == (("s1", "blocr_system"),)
        assert len(result.changes) == 1


# ---------------------------------------------------------------------------
# 旧版 report.json（无 arms 键）回退
# ---------------------------------------------------------------------------

class TestReplayLegacyReport:
    def test_fallback_to_default_toml(self, tmp_path: Path) -> None:
        sample = make_sample("s1", "helo\n", "hello\n")
        out_dir = tmp_path / "out"
        run_initial((sample,), ("noop", "blocr"), {"noop": FakeClient(), "blocr": FakeClient()}, out_dir)

        # 模拟 TOML 系统之前的旧 report：删掉 arms 键
        report_path = out_dir / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report.pop("arms")
        report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

        result = replay_experiment((sample,), out_dir)
        assert set(result.arm_configs) == {"noop", "blocr"}
        assert result.config_warnings  # 回退有告警
        record = next(r for r in result.run_record.records if r.arm == "blocr")
        assert record.corrected_text == "helo\n"  # fake 回原文
        assert result.changes == ()
