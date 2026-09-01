"""report：RunRecord -> 汇总表（markdown 打印 + json 落盘）。

对应 Docs/Design/08-eval-framework.md「指标」「臂配置（TOML）」「验收」节。

- 维度：track × 子集（source_subset）× 臂。
- 指标：cmer_micro / pref_score_cmer_macro（官方 scorer，含 95% CI）、
  tokens_in/out/total 合计、failed 数、配对 output_ratio
  （blocr+system / blocr 同样本 tokens_out 之比的中位数）。
- 自洽校验：每样本 tokens_total == tokens_in + tokens_out，不满足抛 ValueError。
- 每个臂解析后的完整配置写入 report.json：顶层 ``arms.<name>.config``
  （08 文档口径）+ 每个 group 条目的 ``config`` 字段；retries/temperature
  跨臂不一致时写入 ``fairness_warnings``（破坏公平性控制，报告须注明）。
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict
from pathlib import Path

from experiment_app.arm_config import ArmConfig
from experiment_app.run import RunRecord
from experiment_app.score import score_pairs

__all__ = ["build_report", "render_markdown", "write_report"]

PAIR_NUMERATOR_ARM = "blocr_system"
PAIR_DENOMINATOR_ARM = "blocr"


def _validate_consistency(run_record: RunRecord) -> None:
    """自洽校验：每样本 tokens_total == tokens_in + tokens_out，不满足抛错。"""
    for record in run_record.records:
        if record.tokens_total != record.tokens_in + record.tokens_out:
            raise ValueError(
                f"inconsistent token counts for {record.sample_id}/{record.arm}: "
                f"tokens_total={record.tokens_total} != "
                f"tokens_in({record.tokens_in}) + tokens_out({record.tokens_out})"
            )


def _fairness_warnings(arm_configs: dict[str, ArmConfig]) -> list[str]:
    """retries / temperature 跨臂不一致 -> 警告（08 文档：报告须注明）。"""
    knobs = {
        name: (cfg.retries, cfg.temperature)
        for name, cfg in arm_configs.items()
        if cfg.channel != "noop"
    }
    if len(set(knobs.values())) <= 1:
        return []
    detail = ", ".join(f"{n}=(retries={r}, temperature={t})" for n, (r, t) in sorted(knobs.items()))
    return [f"公平性控制被打破：LLM 臂的 (retries, temperature) 不一致：{detail}"]


def build_report(
    run_record: RunRecord,
    *,
    model: str | None = None,
    arm_configs: dict[str, ArmConfig] | None = None,
) -> dict:
    """从 RunRecord 产出结构化汇总 dict；``arm_configs`` 提供时落盘每臂完整配置。"""
    _validate_consistency(run_record)

    samples_by_id = {sample.sample_id: sample for sample in run_record.samples}
    groups: dict[tuple[str, str, str], list] = {}
    for record in run_record.records:
        key = (record.track, record.source_subset, record.arm)
        groups.setdefault(key, []).append(record)

    group_entries: list[dict] = []
    for (track, subset, arm), records in sorted(groups.items()):
        pairs = [(samples_by_id[r.sample_id], r.corrected_text) for r in records]
        scores = score_pairs(pairs)
        averaged = scores["averaged_scores"]
        tokens_in = sum(r.tokens_in for r in records)
        tokens_out = sum(r.tokens_out for r in records)
        tokens_total = sum(r.tokens_total for r in records)
        if tokens_total != tokens_in + tokens_out:  # 聚合层复核
            raise ValueError(
                f"inconsistent aggregated token counts for {track}/{subset}/{arm}"
            )
        entry = {
            "track": track,
            "source_subset": subset,
            "arm": arm,
            "n_samples": len(records),
            "cmer_micro": list(averaged["cmer_micro"]),
            "pref_score_cmer_macro": list(averaged["pref_score_cmer_macro"]),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tokens_total": tokens_total,
            "failed": sum(1 for r in records if r.failed),
        }
        if arm_configs is not None and arm in arm_configs:
            entry["config"] = asdict(arm_configs[arm])
        group_entries.append(entry)

    paired_entries: list[dict] = []
    cells: dict[tuple[str, str], dict[str, dict[str, int]]] = {}
    for record in run_record.records:
        cell = cells.setdefault((record.track, record.source_subset), {})
        cell.setdefault(record.arm, {})[record.sample_id] = record.tokens_out
    for (track, subset), by_arm in sorted(cells.items()):
        num = by_arm.get(PAIR_NUMERATOR_ARM, {})
        den = by_arm.get(PAIR_DENOMINATOR_ARM, {})
        ratios = [
            num[sid] / den[sid]
            for sid in num.keys() & den.keys()
            if den[sid] > 0
        ]
        paired_entries.append(
            {
                "track": track,
                "source_subset": subset,
                "numerator_arm": PAIR_NUMERATOR_ARM,
                "denominator_arm": PAIR_DENOMINATOR_ARM,
                "n_pairs": len(ratios),
                "output_ratio_median": statistics.median(ratios) if ratios else None,
            }
        )

    report: dict = {
        "model": model,
        "track": run_record.track,
        "groups": group_entries,
        "paired_output_ratio": paired_entries,
    }
    if arm_configs is not None:
        report["arms"] = {
            name: {"config": asdict(config)} for name, config in arm_configs.items()
        }
        warnings = _fairness_warnings(arm_configs)
        if warnings:
            report["fairness_warnings"] = warnings
    return report


def _fmt_metric(metric: list[float]) -> str:
    score, lo, hi = metric
    return f"{score:.4f} [{lo:.4f}, {hi:.4f}]"


def render_markdown(report: dict) -> str:
    """汇总 dict -> markdown 表格文本。"""
    lines: list[str] = []
    title = "## 测评汇总"
    if report.get("model"):
        title += f"（model: {report['model']}）"
    lines.append(title)
    lines.append("")
    lines.append(
        "| track | subset | arm | n | cmer_micro | pref_score | "
        "tokens_in | tokens_out | tokens_total | failed |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for g in report["groups"]:
        lines.append(
            f"| {g['track']} | {g['source_subset']} | {g['arm']} | {g['n_samples']} "
            f"| {_fmt_metric(g['cmer_micro'])} | {_fmt_metric(g['pref_score_cmer_macro'])} "
            f"| {g['tokens_in']} | {g['tokens_out']} | {g['tokens_total']} | {g['failed']} |"
        )
    lines.append("")
    lines.append("配对 output_ratio（blocr+system / blocr，tokens_out 中位数）：")
    lines.append("")
    lines.append("| track | subset | n_pairs | output_ratio_median |")
    lines.append("|---|---|---|---|")
    for p in report["paired_output_ratio"]:
        ratio = p["output_ratio_median"]
        ratio_text = f"{ratio:.4f}" if ratio is not None else "n/a"
        lines.append(
            f"| {p['track']} | {p['source_subset']} | {p['n_pairs']} | {ratio_text} |"
        )
    return "\n".join(lines)


def write_report(report: dict, path: Path) -> None:
    """汇总 dict 落盘为 json。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
