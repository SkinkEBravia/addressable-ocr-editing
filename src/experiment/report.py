"""experiment 的报告：report.json + 汇总。

对应 Docs/Design/11-experiment.md「评测与报告」节。

- 磁带经 SessionStore 读回（与 resume 同一代码路径），usage 从 Session 派生。
- 指标语义归数据集，报告只按名聚合。
- token 构成单列（reasoning_tokens 占比）。
- 配对比较：同 task 两工具配置的 output_ratio、Δ指标 + bootstrap 95% CI。
- 失败样本带 failure 段；按 failure.kind 聚合计数。
- 数据集若提供 score_all（聚合口径），其结果一并落盘。
"""

from __future__ import annotations

import itertools
import json
import os
from pathlib import Path, PureWindowsPath
from typing import Any

from datasetkit import ScoreError, load_dataset, resolve
from evalkit import bootstrap_ci, output_ratio, paired_diff_ci
from llm import Usage

from experiment.store import SessionStore

__all__ = ["build_report", "write_report", "resolve_dataset_dir"]


def resolve_dataset_dir(recorded: str) -> Path:
    """报告里记录的数据集目录 -> 本机可用路径。

    记录可能是另一台机器/容器的绝对路径（甚至是异 OS 的路径形式）：
    本机不存在时回退到 ``datasets/<目录名>``（项目布局约定），
    保证 report-only / replay 可移植。
    """
    p = Path(recorded)
    if p.is_dir():
        return p
    name = PureWindowsPath(recorded).name  # Windows 形式（反斜杠）也能取到目录名
    return Path("datasets") / (name or p.name)


def _order_stats(values: list[float]) -> dict[str, float]:
    """次序统计量：median / p90 / max。

    **为什么必须与 mean 并列报告**：本任务的破坏量是重尾的 —— 单个灾难性样本
    足以支配均值。实测 `dta19-doc-1t` 的 `swe_edit`：破坏字符逐篇为
    ``3203 106 90 67 52 46 30 21 12 10 6``，均值 331.2、**中位仅 46**；
    cmer 均值 0.0289 vs 中位 0.0062（差 4.7 倍），bootstrap CI 宽达
    [0.0048, 0.0751]。只看均值会把「1/11 的稀有灾难」误读成「普遍更差」。

    与 `DELEGATE-52`（arXiv:2604.15597 §5）一致：稀疏的灾难性失败解释了
    约 80% 的文档退化。详见 Docs/pitfalls.md #14。
    """
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    median = ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    # 最近秩法：小样本下不插值，避免造出数据里不存在的值
    p90 = ordered[min(n - 1, max(0, -(-n * 9 // 10) - 1))]
    return {"median": median, "p90": p90, "max": ordered[-1]}


def _usage_row(session) -> dict:
    usage = session.usage
    if usage is None:
        return {"usage_missing": True}
    row = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "tokens_total": usage.total,
    }
    if usage.reasoning_tokens is not None and usage.output_tokens > 0:
        row["reasoning_tokens"] = usage.reasoning_tokens
        row["reasoning_share"] = usage.reasoning_tokens / usage.output_tokens
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
    """从磁带 + scorer 构建报告（不重打 API）。"""
    dataset = load_dataset(dataset_dir)
    tasks = {
        t.task_id: t
        for t in resolve(dataset, split=split, keys=loader_keys, meta=meta)
    }
    scorer = dataset.scorer()
    store = SessionStore(out)

    per_sample: dict[str, dict[str, Any]] = {}  # toolset -> task_id -> row
    for name in toolset_names:
        rows: dict[str, Any] = {}
        for task_id, task in tasks.items():
            session = store.read(task_id, name)
            if session is None:
                continue
            output = session.output if session.output is not None else task.input
            row: dict[str, Any] = {
                "status": session.status,
                "turns": len(session.turns),
                "usage": _usage_row(session),
            }
            if session.failure is not None:
                row["failure"] = session.failure.to_dict()
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

    # 聚合：指标均值 + bootstrap CI；token 构成；失败按 kind 计数
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
                agg[metric] = {"mean": mean, "lo": lo, "hi": hi, **_order_stats(values)}
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
        failures: dict[str, int] = {}
        for r in rows.values():
            f = r.get("failure")
            if f:
                kind = f["kind"]
                failures[kind] = failures.get(kind, 0) + 1
        if failures:
            agg["failures"] = failures
        aggregate[name] = agg

    # 配对比较：每对工具配置，同 task 配对
    paired: dict[str, Any] = {}
    for a, b in itertools.combinations(toolset_names, 2):
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
                _usage_obj(per_sample[a][t]["usage"]),
                _usage_obj(per_sample[b][t]["usage"]),
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
                    session = store.read(task_id, name)
                    out_text = session.output if session and session.output is not None else task.input
                    pairs.append((task, out_text))
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


def _usage_obj(row: dict) -> Usage | None:
    if row.get("usage_missing"):
        return None
    return Usage(row["input_tokens"], row["output_tokens"], row.get("reasoning_tokens"))


def write_report(report: dict, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / "report.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path
