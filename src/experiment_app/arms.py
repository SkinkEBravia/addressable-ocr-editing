"""arms：四个测评臂的 runner。

对应 Docs/Design/08-eval-framework.md「臂位」「公平性控制」节。

- ``arm_noop``：control-noop，原样输出（不调 LLM），锚点对照。
- ``arm_blocr``：BLOCR 原样的完全重写通道（渲染 blocr_rewrite -> 解析 JSON）。
- ``arm_blocr_system``：本系统块补丁通道（ingest -> view -> fn patch -> 写回重建）。
- ``arm_ref_blocr_pieces``：ref 臂，按 unit_boundaries 切回单元逐单元重写后拼接
  （仅 doc 轨有意义）。

公平性：两臂重试预算一致（失败后错误信息反馈进 prompt，重试 <= 2 次，共 <= 3 轮），
重试 token 计入总量；超限标记 failed 并回退原文。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import ir
import partition
import reconstruction
import surface
import view
from llm import LLMClient
from sourceio import SourceText

from experiment_app.datasets import DOC_SEPARATOR, Sample
from experiment_app.prompts import render_patch_prompt, render_rewrite_prompt

__all__ = [
    "ArmResult",
    "MAX_RETRIES",
    "arm_noop",
    "arm_blocr",
    "arm_blocr_system",
    "arm_ref_blocr_pieces",
]

MAX_RETRIES = 2
"""失败重试上限（总轮数 = 1 + MAX_RETRIES），两臂一致。"""


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
# blocr 臂（完全重写通道）
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


def _run_blocr(text: str, language: str, client: LLMClient) -> tuple[str, list[dict], bool]:
    """重写通道核心：渲染 -> complete -> 解析 JSON；失败带错误反馈重试。

    返回 (corrected_text, raw_rounds, failed)。
    """
    base_prompt = render_rewrite_prompt(language=language, text=text)
    raw: list[dict] = []
    prompt = base_prompt
    for round_no in range(1, MAX_RETRIES + 2):
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


def arm_noop(sample: Sample, client: LLMClient, workdir: Path) -> ArmResult:
    """control-noop：原样输出，不调 LLM，tokens 0。"""
    return ArmResult(
        corrected_text=sample.ocr_text,
        tokens_in=0,
        tokens_out=0,
        rounds=0,
        failed=False,
        raw=(),
    )


def arm_blocr(sample: Sample, client: LLMClient, workdir: Path) -> ArmResult:
    """blocr 臂：BLOCR 原样的完全重写通道。"""
    corrected, raw, failed = _run_blocr(sample.ocr_text, sample.language, client)
    return _result_from_raw(corrected, raw, failed)


# ---------------------------------------------------------------------------
# blocr+system 臂（fn patch 通道）
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


def arm_blocr_system(sample: Sample, client: LLMClient, workdir: Path) -> ArmResult:
    """blocr+system 臂：原文 -> ingest/view -> LLM 产出 fn patch -> 写回重建。"""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    store = ir.Store(workdir)
    source = SourceText(text=sample.ocr_text, encoding="utf-8", bom=b"")
    snapshot = ir.birth(source, partition.partition_lines(source))
    ir.save(store, snapshot)
    agent_view = view.present(snapshot, view.blockkey_as_is, view.xml_ish)

    base_prompt = render_patch_prompt(language=sample.language, view=agent_view.payload)
    raw: list[dict] = []
    prompt = base_prompt
    for round_no in range(1, MAX_RETRIES + 2):
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
# ref 臂（逐单元重写后拼接）
# ---------------------------------------------------------------------------

def arm_ref_blocr_pieces(sample: Sample, client: LLMClient, workdir: Path) -> ArmResult:
    """ref-blocr@unit-pieces：按 unit_boundaries 切回单元，逐单元跑 blocr 逻辑后拼接。"""
    units = sample.split_units()
    corrected_parts: list[str] = []
    raw: list[dict] = []
    any_failed = False
    for index, unit in enumerate(units):
        corrected, rounds_raw, failed = _run_blocr(unit, sample.language, client)
        corrected_parts.append(corrected)
        any_failed = any_failed or failed
        for entry in rounds_raw:
            raw.append({"unit_index": index, **entry})
    return _result_from_raw(DOC_SEPARATOR.join(corrected_parts), raw, any_failed)
