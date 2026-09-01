"""experiment_app 的测试（对应 Docs/Design/08-eval-framework.md「验收」）。

全部离线，禁止真实 API：LLM 用可编程响应序列的 ScriptClient / 内置 FakeClient。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hipe_ocrepair_scorer import Evaluation, align_records

from experiment_app import score as score_mod
from experiment_app.arm_config import DEFAULT_ARMS_DIR, ArmConfig, build_arm, load_arm_config
from experiment_app.arms import Arm, MAX_RETRIES
from experiment_app.datasets import Sample, load_samples
from experiment_app.report import build_report, render_markdown
from experiment_app.run import DEFAULT_ARM_NAMES, FakeClient, main, run_experiment
from experiment_app.score import score_pairs, write_hyp_jsonl, write_ref_jsonl
from llm import Completion, Usage


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

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


def make_arm(channel: str, **overrides) -> Arm:
    """按通道名装配默认配置的臂（替代旧的硬编码 runner 直调）。"""
    prompt = {
        "noop": "",
        "rewrite": "blocr_rewrite",
        "patch": "blocr_patch",
        "rewrite_pieces": "blocr_rewrite",
    }[channel]
    return build_arm(ArmConfig(name=channel, channel=channel, prompt=prompt, **overrides))


def default_arms_and_clients() -> tuple[dict[str, Arm], dict[str, FakeClient]]:
    """configs/arms/ 四个默认 TOML 装配出的臂 + 每臂独立 FakeClient。"""
    arms = {
        name: build_arm(load_arm_config(name, DEFAULT_ARMS_DIR / f"{name}.toml"))
        for name in DEFAULT_ARM_NAMES
    }
    clients = {name: FakeClient() for name in arms}
    return arms, clients


def make_row(doc_id: str, ocr: str, gold: str, subset: str = "toy", lang: str = "en") -> dict:
    return {
        "document_metadata": {
            "document_id": doc_id,
            "primary_dataset_name": subset,
            "language": lang,
        },
        "ocr_hypothesis": {"transcription_unit": ocr},
        "ground_truth": {"transcription_unit": gold},
    }


def write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    return path


def make_sample(
    sample_id: str = "s1",
    ocr: str = "hello\nworld\n",
    gold: str = "hello\nworld\n",
    track: str = "unit",
    boundaries: tuple[int, ...] = (0,),
) -> Sample:
    return Sample(
        sample_id=sample_id,
        track=track,  # type: ignore[arg-type]
        language="en",
        source_subset="toy",
        ocr_text=ocr,
        gold_text=gold,
        metadata={"document_id": sample_id, "primary_dataset_name": "toy", "language": "en"},
        unit_boundaries=boundaries,
    )


# ---------------------------------------------------------------------------
# datasets
# ---------------------------------------------------------------------------

class TestDatasets:
    ROWS = [
        make_row("docA", "a1 ocr", "a1 gold"),
        make_row("docA", "a2 ocr", "a2 gold"),
        make_row("docB", "b1 ocr", "b1 gold"),
    ]

    def test_unit_track(self, tmp_path: Path) -> None:
        path = write_jsonl(tmp_path / "data.jsonl", self.ROWS)
        samples = load_samples(path, "unit")
        assert len(samples) == 3
        assert samples[0].sample_id == "docA#1"
        assert samples[1].sample_id == "docA#2"
        assert samples[2].sample_id == "docB#3"
        assert samples[0].ocr_text == "a1 ocr"
        assert samples[0].gold_text == "a1 gold"
        assert samples[0].track == "unit"
        assert samples[0].language == "en"
        assert samples[0].source_subset == "toy"
        assert samples[0].metadata["document_id"] == "docA"
        assert all(s.unit_boundaries == (0,) for s in samples)

    def test_doc_track_concat_and_boundaries(self, tmp_path: Path) -> None:
        path = write_jsonl(tmp_path / "data.jsonl", self.ROWS)
        samples = load_samples(path, "doc")
        assert len(samples) == 2
        doc_a, doc_b = samples
        assert doc_a.sample_id == "docA"
        assert doc_a.ocr_text == "a1 ocr\na2 ocr"
        assert doc_a.gold_text == "a1 gold\na2 gold"
        assert doc_a.unit_boundaries == (0, len("a1 ocr") + 1)
        assert doc_a.split_units() == ("a1 ocr", "a2 ocr")
        assert doc_b.sample_id == "docB"
        assert doc_b.ocr_text == "b1 ocr"
        assert doc_b.unit_boundaries == (0,)

    def test_masked_file_skipped_with_warning(self, tmp_path: Path) -> None:
        rows = [make_row("m1", "ocr1", ""), make_row("m2", "ocr2", "")]
        path = write_jsonl(tmp_path / "masked.jsonl", rows)
        with pytest.warns(UserWarning, match="masked"):
            assert load_samples(path, "unit") == ()

    def test_partial_masked_rows_skipped_with_warning(self, tmp_path: Path) -> None:
        rows = self.ROWS[:1] + [make_row("docB", "ocr", "")] + self.ROWS[2:]
        path = write_jsonl(tmp_path / "partial.jsonl", rows)
        with pytest.warns(UserWarning, match="masked"):
            samples = load_samples(path, "unit")
        assert [s.ocr_text for s in samples] == ["a1 ocr", "b1 ocr"]


# ---------------------------------------------------------------------------
# arms
# ---------------------------------------------------------------------------

class TestArmNoop:
    def test_noop(self, tmp_path: Path) -> None:
        sample = make_sample(ocr="raw ocr")
        result = make_arm("noop")(sample, ScriptClient([]), tmp_path)
        assert result.corrected_text == "raw ocr"
        assert result.tokens_in == 0
        assert result.tokens_out == 0
        assert result.rounds == 0
        assert result.failed is False
        assert result.raw == ()


class TestArmBlocr:
    def test_ok(self, tmp_path: Path) -> None:
        client = ScriptClient(['{"ocr_postcorrection_output": "fixed"}'])
        result = make_arm("rewrite")(make_sample(), client, tmp_path)
        assert result.corrected_text == "fixed"
        assert result.failed is False
        assert result.rounds == 1
        assert result.tokens_in == len(client.prompts[0])
        assert result.tokens_out == len('{"ocr_postcorrection_output": "fixed"}')

    def test_markdown_fence_ok(self, tmp_path: Path) -> None:
        client = ScriptClient(['```json\n{"ocr_postcorrection_output": "fenced"}\n```'])
        result = make_arm("rewrite")(make_sample(), client, tmp_path)
        assert result.corrected_text == "fenced"
        assert result.failed is False

    def test_bad_json_retry_then_ok(self, tmp_path: Path) -> None:
        client = ScriptClient(["not json", '{"ocr_postcorrection_output": "ok"}'])
        result = make_arm("rewrite")(make_sample(), client, tmp_path)
        assert result.corrected_text == "ok"
        assert result.failed is False
        assert result.rounds == 2
        assert "ERROR" in client.prompts[1]
        expected_in = sum(len(p) for p in client.prompts)
        assert result.tokens_in == expected_in
        assert result.tokens_out == len("not json") + len('{"ocr_postcorrection_output": "ok"}')

    def test_exhausted_falls_back(self, tmp_path: Path) -> None:
        client = ScriptClient(["bad"] * (MAX_RETRIES + 1))
        sample = make_sample(ocr="original")
        result = make_arm("rewrite")(sample, client, tmp_path)
        assert result.failed is True
        assert result.corrected_text == "original"
        assert result.rounds == MAX_RETRIES + 1
        assert all(entry["error"] for entry in result.raw)


class TestArmBlocrSystem:
    def test_ok_set_content(self, tmp_path: Path) -> None:
        client = ScriptClient(['set_content(b2, "WORLD\\n")'])
        result = make_arm("patch")(make_sample(), client, tmp_path)
        assert result.corrected_text == "hello\nWORLD\n"
        assert result.failed is False
        assert result.rounds == 1

    def test_empty_patch_keeps_original(self, tmp_path: Path) -> None:
        client = ScriptClient([""])
        result = make_arm("patch")(make_sample(), client, tmp_path)
        assert result.corrected_text == "hello\nworld\n"
        assert result.failed is False

    def test_bad_patch_retry_then_ok(self, tmp_path: Path) -> None:
        client = ScriptClient(['remove(b99)', 'set_content(b1, "hi\\n")'])
        result = make_arm("patch")(make_sample(), client, tmp_path)
        assert result.corrected_text == "hi\nworld\n"
        assert result.failed is False
        assert result.rounds == 2
        assert "ERROR" in client.prompts[1]
        assert result.tokens_in == sum(len(p) for p in client.prompts)

    def test_parse_error_retry(self, tmp_path: Path) -> None:
        client = ScriptClient(["this is not a patch", 'set_content(b1, "x\\n")'])
        result = make_arm("patch")(make_sample(), client, tmp_path)
        assert result.corrected_text == "x\nworld\n"
        assert result.failed is False
        assert result.rounds == 2

    def test_exhausted_falls_back(self, tmp_path: Path) -> None:
        client = ScriptClient(["remove(b99)"] * (MAX_RETRIES + 1))
        sample = make_sample(ocr="original")
        result = make_arm("patch")(sample, client, tmp_path)
        assert result.failed is True
        assert result.corrected_text == "original"
        assert result.rounds == MAX_RETRIES + 1


class TestArmRefBlocrPieces:
    def test_pieces(self, tmp_path: Path) -> None:
        u1, u2 = "first unit", "second unit"
        sample = make_sample(
            ocr=u1 + "\n" + u2, track="doc", boundaries=(0, len(u1) + 1)
        )
        client = ScriptClient(
            ['{"ocr_postcorrection_output": "FIRST"}', '{"ocr_postcorrection_output": "SECOND"}']
        )
        result = make_arm("rewrite_pieces")(sample, client, tmp_path)
        assert result.corrected_text == "FIRST\nSECOND"
        assert result.failed is False
        assert result.rounds == 2
        assert result.tokens_in == sum(len(p) for p in client.prompts)
        assert {entry["unit_index"] for entry in result.raw} == {0, 1}


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------

class TestScore:
    def test_hyp_ref_jsonl_accepted_by_official_scorer(self, tmp_path: Path) -> None:
        samples = (
            make_sample("s1", ocr="helo world", gold="hello world"),
            make_sample("s2", ocr="god morning", gold="good morning"),
        )
        corrected = {"s1": "hello world", "s2": "good morning"}

        hyp_path = tmp_path / "hyp.jsonl"
        ref_path = tmp_path / "ref.jsonl"
        write_hyp_jsonl(hyp_path, [(s, corrected[s.sample_id]) for s in samples])
        write_ref_jsonl(ref_path, samples)

        hyp_records = [json.loads(line) for line in hyp_path.read_text(encoding="utf-8").splitlines()]
        ref_records = [json.loads(line) for line in ref_path.read_text(encoding="utf-8").splitlines()]
        assert set(hyp_records[0]) == {
            "document_metadata",
            "ocr_hypothesis",
            "ground_truth",
            "ocr_postcorrection_output",
        }
        assert hyp_records[0]["document_metadata"]["document_id"] == "s1"

        merged = align_records(ref_records, hyp_records)
        results = Evaluation(merged).score_over_datasets(normalize=True)
        assert "cmer_micro" in results["averaged_scores"]
        assert "pref_score_cmer_macro" in results["averaged_scores"]
        # 修复到 gold -> cmer_micro 为 0，pref 全为 +1
        assert results["averaged_scores"]["cmer_micro"][0] == pytest.approx(0.0)
        assert results["averaged_scores"]["pref_score_cmer_macro"][0] == pytest.approx(1.0)

    def test_score_pairs_fields(self) -> None:
        samples = (
            make_sample("s1", ocr="helo world", gold="hello world"),
            make_sample("s2", ocr="god morning", gold="good morning"),
        )
        pairs = [(s, s.ocr_text) for s in samples]
        results = score_pairs(pairs)
        assert "averaged_scores" in results
        assert "fold_scores" in results
        cmer = results["averaged_scores"]["cmer_micro"]
        assert len(cmer) == 3  # (score, lo_ci, hi_ci)
        assert cmer[0] > 0  # 原文有错 -> cMER > 0


# ---------------------------------------------------------------------------
# run + report（端到端，fake 模型）
# ---------------------------------------------------------------------------

class TestRunReport:
    def test_end_to_end(self, tmp_path: Path) -> None:
        rows = [
            make_row("docA", "helo world", "hello world"),
            make_row("docA", "god morning", "good morning"),
            make_row("docB", "ar.d so", "and so"),
        ]
        data = write_jsonl(tmp_path / "dev.jsonl", rows)
        out_dir = tmp_path / "out"

        rc = main(
            [
                "--data", str(data),
                "--track", "unit",
                "--out", str(out_dir),
                "--model", "fake",
            ],
            client_factory=lambda model, temperature=0.2: FakeClient(),
        )
        assert rc == 0

        samples = load_samples(data, "unit")
        assert len(samples) == 3

        # raw 记录落盘存在（sample_id 中的 '#' 被路径消毒为 '_'）
        raw_files = list((out_dir / "raw").rglob("*.json"))
        assert len(raw_files) == 3 * 4  # 3 样本 × 4 臂
        payload = json.loads(
            (out_dir / "raw" / "docA_1" / "blocr.json").read_text(encoding="utf-8")
        )
        assert payload["arm"] == "blocr"
        assert payload["raw"][0]["usage"]["input_tokens"] > 0

        # 汇总 jsonl 落盘
        results_lines = (out_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(results_lines) == 12

        # report.json 落盘且自洽（build_report 内部校验 tokens_total == in + out）
        report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
        assert {g["arm"] for g in report["groups"]} == set(DEFAULT_ARM_NAMES)
        for g in report["groups"]:
            assert g["tokens_total"] == g["tokens_in"] + g["tokens_out"]
            assert g["n_samples"] == 3
            assert g["config"]["channel"]  # 每臂解析后的完整配置落盘
        assert report["arms"]["blocr"]["config"]["channel"] == "rewrite"
        assert report["arms"]["blocr_system"]["config"]["partition"] == "lines"

        # 配对 output_ratio 存在（fake：两臂 tokens_out 均 > 0）
        paired = report["paired_output_ratio"][0]
        assert paired["n_pairs"] == 3
        assert paired["output_ratio_median"] is not None

        # control-noop 的 cmer_micro 与"原文 vs gold"的直接计算一致
        noop_group = next(g for g in report["groups"] if g["arm"] == "noop")
        direct = score_pairs([(s, s.ocr_text) for s in samples])
        assert noop_group["cmer_micro"][0] == pytest.approx(
            direct["averaged_scores"]["cmer_micro"][0]
        )
        # fake 模型：所有臂输出 == 原文，cmer 与 noop 一致
        for g in report["groups"]:
            assert g["cmer_micro"][0] == pytest.approx(noop_group["cmer_micro"][0])

    def test_run_experiment_directly_and_markdown(self, tmp_path: Path) -> None:
        samples = (
            make_sample("s1", ocr="helo\nworld\n", gold="hello\nworld\n"),
            make_sample("s2", ocr="ar.d\n", gold="and\n"),
        )
        arms, clients = default_arms_and_clients()
        record = run_experiment(samples, arms, clients, tmp_path / "out")
        assert len(record.records) == 2 * 4

        report = build_report(record, model="fake")
        markdown = render_markdown(report)
        assert "blocr_system" in markdown
        assert "cmer_micro" in markdown

        # 自洽校验：篡改一条记录必须抛错
        bad = record.records[0]
        tampered = type(bad)(
            **{**bad.__dict__, "tokens_total": bad.tokens_total + 1}
        )
        bad_record = type(record)(
            track=record.track,
            samples=record.samples,
            records=(tampered, *record.records[1:]),
        )
        with pytest.raises(ValueError, match="inconsistent"):
            build_report(bad_record)
