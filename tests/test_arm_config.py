"""arm_config 的测试：TOML 解析 / 默认值 / 未知键报错 / 路径型 prompt / build_arm。

全部离线，禁止真实 API：LLM 用可编程响应序列的 ScriptClient。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiment_app.arm_config import (
    DEFAULT_ARMS_DIR,
    ArmConfig,
    build_arm,
    load_arm_config,
)
from experiment_app.datasets import Sample
from experiment_app.run import DEFAULT_ARM_NAMES, FakeClient, main
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


def make_sample(ocr: str = "hello\nworld\n") -> Sample:
    return Sample(
        sample_id="s1",
        track="unit",
        language="en",
        source_subset="toy",
        ocr_text=ocr,
        gold_text=ocr,
        metadata={"document_id": "s1", "primary_dataset_name": "toy", "language": "en"},
        unit_boundaries=(0,),
    )


def write_toml(tmp_path: Path, text: str, name: str = "arm.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 解析与默认值
# ---------------------------------------------------------------------------

class TestLoadArmConfig:
    def test_default_tomls_load(self) -> None:
        """configs/arms/ 四个默认 TOML 均可解析，字段符合预期。"""
        expected = {
            "noop": ("noop", ""),
            "blocr": ("rewrite", "blocr_rewrite"),
            "blocr_system": ("patch", "blocr_patch"),
            "ref_blocr_pieces": ("rewrite_pieces", "blocr_rewrite"),
        }
        assert set(DEFAULT_ARM_NAMES) == set(expected)
        for name, (channel, prompt) in expected.items():
            config = load_arm_config(name, DEFAULT_ARMS_DIR / f"{name}.toml")
            assert config.name == name
            assert config.channel == channel
            assert config.prompt == prompt
            assert config.retries == 2
            assert config.temperature == pytest.approx(0.2)
        system = load_arm_config("blocr_system", DEFAULT_ARMS_DIR / "blocr_system.toml")
        assert system.partition == "lines"
        assert system.block_size == 400

    def test_defaults_filled(self, tmp_path: Path) -> None:
        path = write_toml(tmp_path, 'channel = "rewrite"\nprompt = "blocr_rewrite"\n')
        config = load_arm_config("x", path)
        assert config.retries == 2
        assert config.temperature == pytest.approx(0.2)
        assert config.partition == "lines"
        assert config.block_size == 400
        assert config.prompt_base_dir == str(tmp_path)

    def test_noop_needs_no_prompt(self, tmp_path: Path) -> None:
        path = write_toml(tmp_path, 'channel = "noop"\n')
        config = load_arm_config("n", path)
        assert config.prompt == ""

    def test_unknown_top_level_key_rejected(self, tmp_path: Path) -> None:
        path = write_toml(
            tmp_path, 'channel = "rewrite"\nprompt = "p"\nretriess = 3\n'
        )
        with pytest.raises(ValueError, match="未知键.*retriess"):
            load_arm_config("x", path)

    def test_unknown_patch_key_rejected(self, tmp_path: Path) -> None:
        path = write_toml(
            tmp_path,
            'channel = "patch"\nprompt = "p"\n[patch]\npartiton = "lines"\n',
        )
        with pytest.raises(ValueError, match=r"\[patch\] 段.*partiton"):
            load_arm_config("x", path)

    def test_unknown_channel_rejected(self, tmp_path: Path) -> None:
        path = write_toml(tmp_path, 'channel = "magic"\nprompt = "p"\n')
        with pytest.raises(ValueError, match="channel"):
            load_arm_config("x", path)

    def test_llm_channel_requires_prompt(self, tmp_path: Path) -> None:
        path = write_toml(tmp_path, 'channel = "rewrite"\n')
        with pytest.raises(ValueError, match="prompt"):
            load_arm_config("x", path)

    def test_frozen(self, tmp_path: Path) -> None:
        path = write_toml(tmp_path, 'channel = "noop"\n')
        config = load_arm_config("x", path)
        with pytest.raises(AttributeError):
            config.retries = 9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 路径型 prompt
# ---------------------------------------------------------------------------

class TestPathPrompt:
    def test_path_prompt_resolved_relative_to_toml(self, tmp_path: Path) -> None:
        (tmp_path / "tpl.md").write_text(
            "CUSTOM TEMPLATE {language}\n"
            "--- OCR TEXT (language: {language}) ---\n{text}\n--- END OF OCR TEXT ---\n",
            encoding="utf-8",
        )
        path = write_toml(tmp_path, 'channel = "rewrite"\nprompt = "tpl.md"\n')
        config = load_arm_config("custom", path)

        client = ScriptClient(['{"ocr_postcorrection_output": "done"}'])
        arm = build_arm(config)
        result = arm(make_sample(), client, tmp_path / "wd")
        assert result.corrected_text == "done"
        assert client.prompts[0].startswith("CUSTOM TEMPLATE en")

    def test_package_prompt_name_still_works(self, tmp_path: Path) -> None:
        path = write_toml(tmp_path, 'channel = "rewrite"\nprompt = "blocr_rewrite"\n')
        config = load_arm_config("pkg", path)
        client = ScriptClient(['{"ocr_postcorrection_output": "done"}'])
        result = build_arm(config)(make_sample(), client, tmp_path / "wd")
        assert result.corrected_text == "done"
        assert "OCR post-correction" in client.prompts[0]  # 包内模板内容


# ---------------------------------------------------------------------------
# build_arm 四通道
# ---------------------------------------------------------------------------

class TestBuildArm:
    def _arm(self, channel: str, **overrides):
        prompt = {
            "noop": "",
            "rewrite": "blocr_rewrite",
            "patch": "blocr_patch",
            "rewrite_pieces": "blocr_rewrite",
        }[channel]
        return build_arm(ArmConfig(name=channel, channel=channel, prompt=prompt, **overrides))

    def test_noop(self, tmp_path: Path) -> None:
        result = self._arm("noop")(make_sample(), ScriptClient([]), tmp_path)
        assert result.corrected_text == "hello\nworld\n"
        assert result.rounds == 0

    def test_rewrite(self, tmp_path: Path) -> None:
        client = ScriptClient(['{"ocr_postcorrection_output": "fixed"}'])
        result = self._arm("rewrite")(make_sample(), client, tmp_path)
        assert result.corrected_text == "fixed"

    def test_patch(self, tmp_path: Path) -> None:
        client = ScriptClient(['set_content(b2, "WORLD\\n")'])
        result = self._arm("patch")(make_sample(), client, tmp_path)
        assert result.corrected_text == "hello\nWORLD\n"

    def test_rewrite_pieces(self, tmp_path: Path) -> None:
        client = ScriptClient(
            ['{"ocr_postcorrection_output": "FIRST"}', '{"ocr_postcorrection_output": "SECOND"}']
        )
        u1, u2 = "first unit", "second unit"
        sample = Sample(
            sample_id="d1", track="doc", language="en", source_subset="toy",
            ocr_text=u1 + "\n" + u2, gold_text=u1 + "\n" + u2,
            metadata={"document_id": "d1"}, unit_boundaries=(0, len(u1) + 1),
        )
        result = self._arm("rewrite_pieces")(sample, client, tmp_path)
        assert result.corrected_text == "FIRST\nSECOND"

    def test_retries_from_config(self, tmp_path: Path) -> None:
        """retries=0 时不重试：一次失败即回退。"""
        client = ScriptClient(["bad"])
        result = self._arm("rewrite", retries=0)(make_sample(), client, tmp_path)
        assert result.failed is True
        assert result.rounds == 1
        assert result.corrected_text == "hello\nworld\n"

    def test_patch_chars_partition(self, tmp_path: Path) -> None:
        """partition="chars" 时按 block_size 定长分块。"""
        client = ScriptClient(['set_content(b1, "HELLO")'])
        arm = self._arm("patch", partition="chars", block_size=5)
        result = arm(make_sample(), client, tmp_path)
        # 块：b1="hello", b2="\nworl", b3="d\n"
        assert result.corrected_text == "HELLO\nworld\n"
        assert '<x id="b3"\\>' in client.prompts[0]


# ---------------------------------------------------------------------------
# CLI：--arm-config 变体同跑
# ---------------------------------------------------------------------------

class TestCliArmConfig:
    def test_arm_config_variant(self, tmp_path: Path) -> None:
        row = {
            "document_metadata": {
                "document_id": "d1", "primary_dataset_name": "toy", "language": "en",
            },
            "ocr_hypothesis": {"transcription_unit": "helo world"},
            "ground_truth": {"transcription_unit": "hello world"},
        }
        data = tmp_path / "dev.jsonl"
        data.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

        out_dir = tmp_path / "out"
        rc = main(
            [
                "--data", str(data),
                "--track", "unit",
                "--out", str(out_dir),
                "--model", "fake",
                "--arms", "blocr_system",
                "--arm-config", f"sys_v2={DEFAULT_ARMS_DIR / 'blocr_system.toml'}",
            ],
            client_factory=lambda model, temperature=0.2: FakeClient(),
        )
        assert rc == 0
        report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
        assert {g["arm"] for g in report["groups"]} == {"blocr_system", "sys_v2"}
        # 同通道两变体同跑：标签区分，配置落盘
        assert report["arms"]["sys_v2"]["config"]["channel"] == "patch"
        assert report["arms"]["sys_v2"]["config"]["name"] == "sys_v2"

    def test_missing_arm_toml_clear_error(self, tmp_path: Path) -> None:
        row = {
            "document_metadata": {
                "document_id": "d1", "primary_dataset_name": "toy", "language": "en",
            },
            "ocr_hypothesis": {"transcription_unit": "x"},
            "ground_truth": {"transcription_unit": "x"},
        }
        data = tmp_path / "dev.jsonl"
        data.write_text(json.dumps(row) + "\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="arm 配置不存在"):
            main(
                [
                    "--data", str(data),
                    "--track", "unit",
                    "--out", str(tmp_path / "out"),
                    "--arms", "no_such_arm",
                ],
                client_factory=lambda model, temperature=0.2: FakeClient(),
            )

    def test_per_arm_temperature_passed_to_factory(self, tmp_path: Path) -> None:
        """每臂独立 client：temperature 透传给 factory。"""
        row = {
            "document_metadata": {
                "document_id": "d1", "primary_dataset_name": "toy", "language": "en",
            },
            "ocr_hypothesis": {"transcription_unit": "x"},
            "ground_truth": {"transcription_unit": "x"},
        }
        data = tmp_path / "dev.jsonl"
        data.write_text(json.dumps(row) + "\n", encoding="utf-8")
        custom = write_toml(
            tmp_path,
            'channel = "rewrite"\nprompt = "blocr_rewrite"\ntemperature = 0.7\nretries = 0\n',
            name="hot.toml",
        )

        seen: list[float] = []

        def factory(model: str, *, temperature: float = 0.2):
            seen.append(temperature)
            return FakeClient()

        rc = main(
            [
                "--data", str(data),
                "--track", "unit",
                "--out", str(tmp_path / "out"),
                "--model", "fake",
                "--arms", "blocr",
                "--arm-config", f"hot={custom}",
            ],
            client_factory=factory,
        )
        assert rc == 0
        assert sorted(seen) == [0.2, 0.7]
        # 温度跨臂不一致 -> 公平性警告落盘
        report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
        assert any("公平性" in w for w in report["fairness_warnings"])
