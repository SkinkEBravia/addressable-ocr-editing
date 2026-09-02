"""experiment 的报告：report.json + 汇总。

对应 Docs/Design/11-experiment.md「报告」节。

- 指标语义归数据集，报告只按名聚合。
- token 构成单列（reasoning_tokens 占比）。
- 配对比较：同 task 两工具配置的 output_ratio、Δ指标 + bootstrap 95% CI。
- 解析后的全部配置落盘，可复现可审计。
- 数据集若提供 score_all（聚合口径），其结果一并落盘。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from datasetkit import ScoreError, load_dataset, resolve
from evalkit import bootstrap_ci, output_ratio, paired_diff_ci

__all__ = ["build_report", "write_report"]


def _usage_row(total: dict | None) -> dict:
    if total is None:
        return {"usage_missing": True}
    row = {
        "input_tokens": total["input_tokens"],
        "output_tokens": total["output_tokens"],
        "tokens_total": total["input_tokens"] + total["output_tokens"],
    }
    reasoning = total.get("reasoning_tokens")
    if reasoning is not None and total["output_tokens"] > 0:
        row["reasoning_tokens"] = reasoning
        row["reasoning_share"] = reasoning / total["output_tokens"]
    return row


def build_report(
    *,
    dataset_dir: Path,
    split: str,
    out: Path,
    toolset_names: list[str],
    model_config_dicts: dict[str, dict],
    toolset_config_dicts: dict[str, dict],
    instruction: str | None,
    loader_keys: list[str] | None = None,
    meta: dict[str, str] | None = None,
) -> dict:
    """从对话录 + scorer 构建报告（不重打 API）。"""
    dataset = load_dataset(dataset_dir)
    tasks = {
        t.task_id: t
        for t in resolve(dataset, split=split, keys=loader_keys, meta=meta)
    }
    scorer = dataset.scorer()

    raw_root = out / "raw"
    per_sample: dict[str, dict[str, Any]] = {}  # toolset -> task_id -> row
    for name in toolset_names:
        rows: dict[str, Any] = {}
        for task_id, task in tasks.items():
            path = raw_root / task_id / f"{name}.json"
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            output = data.get("output", task.input)
            row: dict[str, Any] = {
                "status": data.get("status"),
                "turns": len(data.get("turns", [])),
                "usage": _usage_row(data.get("total_usage")),
            }
            if task.reference is None:
                row["score"] = None  # masked 不出数
            else:
                try:
                    row["score"] = scorer.score(output, task)
                except ScoreError as exc:
                    row["score"] = None
                    row["score_error"] = str(exc)
            rows[task_id] = row
        per_sample[name] = rows

    # 聚合：指标均值 + bootstrap CI；token 构成
    aggregate: dict[str, Any] = {}
    metric_names: set[str] = set()
    for rows in per_sample.values():
        for row in rows.values():
            if row.get("score"):
                metric_names.update(row["score"])
    for name, rows in per_sample.items():
        scored = [r for r in rows.values() if r.get("score")]
        agg: dict[str, Any] = {"n_scored": len(scored), "n_total": len(rows)}
        for metric in sorted(metric_names):
            values = [r["score"][metric] for r in scored if metric in r["score"]]
            if values:
                mean, lo, hi = bootstrap_ci(values)
                agg[metric] = {"mean": mean, "lo": lo, "hi": hi}
        usages = [r["usage"] for r in rows.values() if not r["usage"].get("usage_missing")]
        if usages:
            total_in = sum(u["input_tokens"] for u in usages)
            total_out = sum(u["output_tokens"] for u in usages)
            agg["tokens"] = {"input": total_in, "output": total_out, "total": total_in + total_out}
            reasoning = [u.get("reasoning_tokens") for u in usages]
            if all(isinstance(r, int) for r in reasoning):
                agg["tokens"]["reasoning"] = sum(reasoning)  # type: ignore[arg-type]
                if total_out:
                    agg["tokens"]["reasoning_share"] = sum(reasoning) / total_out  # type: ignore[arg-type]
        aggregate[name] = agg

    # 配对比较：每对工具配置，同 task 配对
    paired: dict[str, Any] = {}
    for i, a in enumerate(toolset_names):
        for b in toolset_names[i + 1 :]:
            common = [
                t
                for t in per_sample.get(a, {})
                if t in per_sample.get(b, {})
                and per_sample[a][t].get("score")
                and per_sample[b][t].get("score")
            ]
            if not common:
                continue
            entry: dict[str, Any] = {}
            ratios = [
                output_ratio(
                    None
                    if per_sample[a][t]["usage"].get("usage_missing")
                    else _usage_obj(per_sample[a][t]["usage"]),
                    None
                    if per_sample[b][t]["usage"].get("usage_missing")
                    else _usage_obj(per_sample[b][t]["usage"]),
                )
                for t in common
            ]
            ratios = [r for r in ratios if r is not None]
            if ratios:
                mean, lo, hi = bootstrap_ci(ratios)
                entry["output_ratio"] = {"mean": mean, "lo": lo, "hi": hi}
            for metric in sorted(metric_names):
                va = [per_sample[a][t]["score"].get(metric) for t in common]
                vb = [per_sample[b][t]["score"].get(metric) for t in common]
                pairs = [(x, y) for x, y in zip(va, vb) if x is not None and y is not None]
                if pairs:
                    mean, lo, hi = paired_diff_ci(
                        [x for x, _ in pairs], [y for _, y in pairs]
                    )
                    entry[f"delta_{metric}"] = {"mean": mean, "lo": lo, "hi": hi}
            paired[f"{a} vs {b}"] = entry

    # 数据集聚合口径（若数据集提供 score_all）
    official: dict[str, Any] = {}
    score_all = getattr(dataset, "score_all", None)
    if callable(score_all):
        for name in toolset_names:
            rows = per_sample.get(name, {})
            pairs = []
            for task_id, row in rows.items():
                task = tasks[task_id]
                if task.reference is not None and row.get("status") is not None:
                    raw_path = raw_root / task_id / f"{name}.json"
                    data = json.loads(raw_path.read_text(encoding="utf-8"))
                    pairs.append((task, data.get("output", task.input)))
            if pairs:
                try:
                    official[name] = score_all(pairs)
                except Exception as exc:  # 聚合口径失败不阻断报告
                    official[name] = {"error": str(exc)}

    return {
        "dataset": {
            "dir": str(Path(dataset_dir).resolve()),
            "split": split,
            "loader_keys": loader_keys,
            "meta": meta,
            "info": vars(dataset.info()),
        },
        "models": model_config_dicts,
        "toolsets": toolset_config_dicts,
        "instruction_source": "override" if instruction is not None else "dataset_default",
        "per_sample": per_sample,
        "aggregate": aggregate,
        "paired": paired,
        "official": official,
    }


def _usage_obj(row: dict):
    from llm import Usage

    return Usage(row["input_tokens"], row["output_tokens"], row.get("reasoning_tokens"))


def write_report(report: dict, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / "report.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path
