"""HIPE / Experiment 报告指标提取与 Markdown 表格生成脚本。

用法:
    uv run python scripts/report_summary.py <report.json 路径> [<更多 report.json> ...]

功能:
    1. 动态自适应提取各 arm 的指标（无需硬编码 arm 名称）；
    2. 输出规范的实验结果 Markdown 表格（cMER CI、Δ noop CI、fixed/missed/broken/halluc_ins、tokens、reasoning 占比）；
    3. 输出配对统计（paired differences）及 95% CI；
    4. 输出官方聚合口径指标（Micro-cMER、Macro-cMER、Macro-wMER、Preference Score）；
    5. 报告异常与失败统计（failures）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def fmt_ci(val_dict: dict | None, is_pct: bool = False, digits: int = 4) -> str:
    if not val_dict or "mean" not in val_dict:
        return "—"
    mean = val_dict["mean"]
    lo = val_dict.get("lo", mean)
    hi = val_dict.get("hi", mean)
    if is_pct:
        return f"{mean*100:.2f}% [{lo*100:.2f}%, {hi*100:.2f}%]"
    fmt = f"{{:.{digits}f}}"
    return f"{fmt.format(mean)} [{fmt.format(lo)}, {fmt.format(hi)}]"


def fmt_val(val_dict: dict | None, is_pct: bool = False, digits: int = 4) -> str:
    if not val_dict or "mean" not in val_dict:
        return "—"
    mean = val_dict["mean"]
    if is_pct:
        return f"{mean*100:.2f}%"
    fmt = f"{{:.{digits}f}}"
    return fmt.format(mean)


def fmt_tokens(tokens_dict: dict | None) -> tuple[str, str, str]:
    """返回 (in_str, out_str, reasoning_share_str)。"""
    if not tokens_dict:
        return "0", "0", "—"
    
    def _scale(n: int) -> str:
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.1f}k"
        return str(n)

    in_tokens = _scale(tokens_dict.get("input", 0))
    out_tokens = _scale(tokens_dict.get("output", 0))
    share = tokens_dict.get("reasoning_share")
    share_str = f"{share*100:.1f}%" if share is not None else "—"
    return in_tokens, out_tokens, share_str


def summarize_report(report_path: Path | str) -> None:
    p = Path(report_path)
    if not p.exists():
        print(f"[Error] File not found: {p}", file=sys.stderr)
        return

    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"\n{'='*20} {p} {'='*20}")
    toolsets = list(data.get("toolsets", {}).keys())
    agg: dict[str, Any] = data.get("aggregate", {})
    paired: dict[str, Any] = data.get("paired", {})
    official: dict[str, Any] = data.get("official", {})

    # 确定排序：noop 排第一，其余按 toolsets 顺序或字典序
    all_arms = list(dict.fromkeys((["noop"] if "noop" in agg else []) + [t for t in toolsets if t in agg] + list(agg.keys())))

    # 打印样本量与状态
    scored_info = [f"{arm}: {agg[arm].get('n_scored', 0)}/{agg[arm].get('n_total', 0)}" for arm in all_arms]
    print(f"Scored/Total: {', '.join(scored_info)}")

    print("\n### Markdown 结果表格\n")
    header = "| arm | cmer ↓ [95% CI] | Δ vs noop [CI] | fixed ↑ | missed ↓ | broken ↓ | halluc ↓ | out tokens | reasoning 占比 |"
    sep = "|---|---|---|---|---|---|---|---|---|"
    print(header)
    print(sep)

    for arm in all_arms:
        a = agg.get(arm, {})
        cmer_str = fmt_ci(a.get("cmer"), digits=4)

        # delta vs noop (arm - noop: 正为劣化，负为改善)
        delta_str = "—"
        if arm != "noop" and "noop" in agg:
            k_noop_vs_arm = f"noop vs {arm}"
            k_arm_vs_noop = f"{arm} vs noop"
            if k_noop_vs_arm in paired and "delta_cmer" in paired[k_noop_vs_arm]:
                # paired_diff_ci(a, b) = a - b = noop - arm
                # arm - noop = -(noop - arm)
                d = paired[k_noop_vs_arm]["delta_cmer"]
                mean, lo, hi = -d["mean"], -d["hi"], -d["lo"]
                delta_str = f"{mean:+.4f} [{lo:+.4f}, {hi:+.4f}]"
            elif k_arm_vs_noop in paired and "delta_cmer" in paired[k_arm_vs_noop]:
                d = paired[k_arm_vs_noop]["delta_cmer"]
                mean, lo, hi = d["mean"], d["lo"], d["hi"]
                delta_str = f"{mean:+.4f} [{lo:+.4f}, {hi:+.4f}]"

        fixed_str = fmt_val(a.get("fixed_rate"), is_pct=True)
        missed_str = fmt_val(a.get("missed_rate"), is_pct=True)
        broken_str = fmt_val(a.get("broken_rate"), is_pct=True)
        halluc_str = fmt_val(a.get("halluc_ins"), is_pct=True)
        _, out_tokens_str, share_str = fmt_tokens(a.get("tokens"))

        print(f"| {arm} | {cmer_str} | {delta_str} | {fixed_str} | {missed_str} | {broken_str} | {halluc_str} | {out_tokens_str} | {share_str} |")

    # 配对比较详情
    if paired:
        print("\n### 配对比较（Paired Differences 95% CI）\n")
        for pair_name, v in paired.items():
            if "delta_cmer" in v:
                d = v["delta_cmer"]
                print(f"- `{pair_name}`: Δ_cmer = {d['mean']:+.4f} [{d['lo']:+.4f}, {d['hi']:+.4f}]")

    # 官方聚合口径
    if official:
        print("\n### 官方聚合口径（score_all）\n")
        print("| arm | cMER micro ↓ | cMER macro ↓ | wMER macro ↓ | Pref Score (cMER) ↑ |")
        print("|---|---|---|---|---|")
        for arm in all_arms:
            off = official.get(arm, {}).get("averaged_scores", {})
            if not off:
                continue
            c_micro = off.get("cmer_micro", [0])[0]
            c_macro = off.get("cmer_macro", [0])[0]
            w_macro = off.get("wmer_macro", [0])[0]
            pref = off.get("pref_score_cmer_macro", [0])[0]
            print(f"| {arm} | {c_micro:.4f} | {c_macro:.4f} | {w_macro:.4f} | {pref:+.4f} |")

    # 异常统计
    failures_found = False
    for arm in all_arms:
        fails = agg.get(arm, {}).get("failures")
        if fails:
            if not failures_found:
                print("\n### 异常样本统计（Failures）\n")
                failures_found = True
            print(f"- `{arm}`: {fails}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/report_summary.py <report.json> ...", file=sys.stderr)
        sys.exit(1)

    for arg in sys.argv[1:]:
        summarize_report(arg)


if __name__ == "__main__":
    main()
