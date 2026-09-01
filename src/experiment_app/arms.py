"""arms：四条执行通道的 runner（noop / rewrite / patch / rewrite_pieces）。

对应 Docs/Design/08-eval-framework.md「臂位」「臂配置（TOML）」「公平性控制」节。

- ``arm_noop``：control-noop，原样输出（不调 LLM），锚点对照。
- ``arm_rewrite``：完全重写通道（渲染 rewrite 模板 -> 解析 JSON）。
- ``arm_patch``：本系统块补丁通道（ingest -> view -> fn patch -> 写回重建）。
- ``arm_rewrite_pieces``：ref 臂，按 unit_boundaries 切回单元逐单元重写后拼接
  （仅 doc 轨有意义）。

实验旋钮（重试预算 / 模板 / 分区方式 / 块大小）全部来自 ArmConfig（TOML），
不再硬编码。公平性：失败后错误信息反馈进 prompt，重试次数为臂级配置
（跨臂不一致时由报告注明）；重试 token 计入总量；超限标记 failed 并回退原文。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import ir
import partition
import reconstruction
import surface
import view
from llm import LLMClient
from sourceio import SourceText

from experiment_app.datasets import DOC_SEPARATOR, Sample
from experiment_app.prompts import render_patch_prompt, render_rewrite_prompt

if TYPE_CHECKING:
    from experiment_app.arm_config import ArmConfig

__all__ = [
    "Arm",
    "ArmResult",
    "MAX_RETRIES",
    "arm_noop",
    "arm_rewrite",
    "arm_patch",
    "arm_rewrite_pieces",
]

MAX_RETRIES = 2
"""默认失败重试上限（总轮数 = 1 + retries）；ArmConfig.retries 缺省值的来源。"""

Arm = Callable[[Sample, LLMClient, Path], "ArmResult"]
"""臂签名：(sample, client, workdir) -> ArmResult。"""


@dataclass(frozen=True)
class ArmResult:
    """单样本单臂的执行结果。"""

    corrected_text: str
    tokens_in: int
    tokens_out: int
    rounds: int
    failed: bool
    raw: tuple[dict, ...]
    """每轮原始记录：{"round", "prompt", "response", "usage", "error"}。"""


# ---------------------------------------------------------------------------
# rewrite 通道（完全重写）
# ---------------------------------------------------------------------------

def _extract_json_object(response: str) -> dict:
    """从响应中取第一个 JSON 对象（容忍 markdown fence / 前后噪声）。"""
    start = response.find("{")
    if start < 0:
        raise ValueError("response contains no JSON object")
    obj, _ = json.JSONDecoder().raw_decode(response[start:])
    if not isinstance(obj, dict):
        raise ValueError("top-level JSON value is not an object")
    return obj


def _extract_corrected(response: str) -> str:
    obj = _extract_json_object(response)
    value = obj.get("ocr_postcorrection_output")
    if not isinstance(value, str):
        raise ValueError("missing string field 'ocr_postcorrection_output'")
    return value


def _run_rewrite(
    text: str, language: str, client: LLMClient, config: ArmConfig
) -> tuple[str, list[dict], bool]:
    """重写通道核心：渲染 -> complete -> 解析 JSON；失败带错误反馈重试。

    返回 (corrected_text, raw_rounds, failed)。
    """
    base_prompt = render_rewrite_prompt(
        language=language, text=text, prompt=config.prompt, base_dir=config.prompt_base_dir or None
    )
    raw: list[dict] = []
    prompt = base_prompt
    for round_no in range(1, config.retries + 2):
        completion = client.complete(prompt)
        entry = {
            "round": round_no,
            "prompt": prompt,
            "response": completion.text,
            "usage": {
                "input_tokens": completion.usage.input_tokens,
                "output_tokens": completion.usage.output_tokens,
            },
            "error": None,
        }
        try:
            corrected = _extract_corrected(completion.text)
        except ValueError as exc:
            entry["error"] = str(exc)
            raw.append(entry)
            prompt = (
                base_prompt
                + "\n\nERROR: your previous response could not be parsed: "
                + str(exc)
                + "\nReturn the JSON object only."
            )
            continue
        raw.append(entry)
        return corrected, raw, False
    return text, raw, True


def _result_from_raw(corrected: str, raw: list[dict], failed: bool) -> ArmResult:
    return ArmResult(
        corrected_text=corrected,
        tokens_in=sum(e["usage"]["input_tokens"] for e in raw),
        tokens_out=sum(e["usage"]["output_tokens"] for e in raw),
        rounds=len(raw),
        failed=failed,
        raw=tuple(raw),
    )


def arm_noop(config: ArmConfig, sample: Sample, client: LLMClient, workdir: Path) -> ArmResult:
    """control-noop：原样输出，不调 LLM，tokens 0。"""
    return ArmResult(
        corrected_text=sample.ocr_text,
        tokens_in=0,
        tokens_out=0,
        rounds=0,
        failed=False,
        raw=(),
    )


def arm_rewrite(config: ArmConfig, sample: Sample, client: LLMClient, workdir: Path) -> ArmResult:
    """rewrite 通道：完全重写（BLOCR 原样的输出通道为默认模板）。"""
    corrected, raw, failed = _run_rewrite(sample.ocr_text, sample.language, client, config)
    return _result_from_raw(corrected, raw, failed)


# ---------------------------------------------------------------------------
# patch 通道（fn patch）
# ---------------------------------------------------------------------------

def _error_feedback(exc: Exception) -> str:
    """把 ParseError / SurfaceError 的结构化信息整理成反馈文本。"""
    if isinstance(exc, surface.ParseError):
        detail = f"parse error at line {exc.line}: {exc.reason}"
    elif isinstance(exc, surface.SurfaceError):
        detail = f"{exc.stage} error: {exc}"
    else:  # pragma: no cover - 防御
        detail = f"{type(exc).__name__}: {exc}"
    return (
        "\n\nERROR: your previous patch was rejected: "
        + detail
        + "\nOutput the corrected patch only. No explanation, no markdown fences."
    )


def _partition_source(source: SourceText, config: ArmConfig) -> partition.PartitionResult:
    """按臂配置选择分区方式：lines 按行；chars 按 config.block_size 定长。"""
    if config.partition == "chars":
        return partition.partition_chars(source, config.block_size)
    return partition.partition_lines(source)


def arm_patch(config: ArmConfig, sample: Sample, client: LLMClient, workdir: Path) -> ArmResult:
    """patch 通道：原文 -> ingest/view -> LLM 产出 fn patch -> 写回重建。"""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    store = ir.Store(workdir)
    source = SourceText(text=sample.ocr_text, encoding="utf-8", bom=b"")
    snapshot = ir.birth(source, _partition_source(source, config))
    ir.save(store, snapshot)
    agent_view = view.present(snapshot, view.blockkey_as_is, view.xml_ish)

    base_prompt = render_patch_prompt(
        language=sample.language,
        view=agent_view.payload,
        prompt=config.prompt,
        base_dir=config.prompt_base_dir or None,
    )
    raw: list[dict] = []
    prompt = base_prompt
    for round_no in range(1, config.retries + 2):
        completion = client.complete(prompt)
        entry = {
            "round": round_no,
            "prompt": prompt,
            "response": completion.text,
            "usage": {
                "input_tokens": completion.usage.input_tokens,
                "output_tokens": completion.usage.output_tokens,
            },
            "error": None,
        }
        try:
            result = surface.run_patch(
                store, completion.text, view.blockkey_as_is, view.xml_ish
            )
        except (surface.ParseError, surface.SurfaceError) as exc:
            entry["error"] = _error_feedback(exc).strip()
            raw.append(entry)
            prompt = base_prompt + _error_feedback(exc)
            continue
        raw.append(entry)
        new_snapshot = ir.load(store, result.snapshot_id)
        corrected = reconstruction.reconstruct(new_snapshot).text
        return _result_from_raw(corrected, raw, False)
    return _result_from_raw(sample.ocr_text, raw, True)


# ---------------------------------------------------------------------------
# rewrite_pieces 通道（ref 臂：逐单元重写后拼接）
# ---------------------------------------------------------------------------

def arm_rewrite_pieces(
    config: ArmConfig, sample: Sample, client: LLMClient, workdir: Path
) -> ArmResult:
    """rewrite_pieces 通道：按 unit_boundaries 切回单元，逐单元重写后拼接。"""
    units = sample.split_units()
    corrected_parts: list[str] = []
    raw: list[dict] = []
    any_failed = False
    for index, unit in enumerate(units):
        corrected, rounds_raw, failed = _run_rewrite(unit, sample.language, client, config)
        corrected_parts.append(corrected)
        any_failed = any_failed or failed
        for entry in rounds_raw:
            raw.append({"unit_index": index, **entry})
    return _result_from_raw(DOC_SEPARATOR.join(corrected_parts), raw, any_failed)
