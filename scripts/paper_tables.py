"""Generate all-arm and noise-stratified descriptive tables from the snapshot."""
import csv
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = {
    "noop": "No edit", "find-replace": "Global F/R", "find-replace-numkey": "Global + keys",
    "find-replace-blocked": "Blocked F/R", "patch-find-replace": "Local patch",
    "patch-find-replace-noatt": "Patch no-attn", "patch-find-replace-unstable": "Unstable local",
    "rewrite": "Rewrite", "rewrite-numkey": "Rewrite + keys",
}


def main():
    with (ROOT / "paper/data/results.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    details, tables = [], []
    for model, title in [("v4", "DeepSeek V4 Flash"), ("v41", "DeepSeek V4.1 Flash"), ("m3", "MiniMax M3")]:
        baseline = {r["task_id"]: float(r["cmer"]) for r in rows if r["model"] == model and r["arm"] == "noop"}
        lines = [r"\begin{table}[htbp]\centering\small",
                 rf"\caption{{All arms for {title}. Counts use all 33 tasks. Worse means cMER exceeds the no-edit anchor; it is not a count of catastrophic errors.}}",
                 r"\begin{tabular}{lrrrrrrr}\toprule",
                 r"Arm & Median & P90 & Max & Done & Edited & Worse & Leak\\\midrule"]
        for arm, label in LABELS.items():
            subset = [r for r in rows if r["model"] == model and r["arm"] == arm]
            vals = sorted(float(r["cmer"]) for r in subset)
            done = sum(r["status"] == "done" for r in subset)
            edited = sum(float(r["edit_spans"]) > 0 for r in subset)
            worse = sum(float(r["cmer"]) > baseline[r["task_id"]] for r in subset)
            leak = sum(float(r["key_leak"]) > 0 for r in subset)
            lines.append(f"{label} & {statistics.median(vals):.4f} & {vals[int(.9 * len(vals))]:.4f} & {max(vals):.4f} & {done} & {edited} & {worse} & {leak}" + r"\\")
            for noise in sorted({r["noise"] for r in subset}):
                part = [r for r in subset if r["noise"] == noise]
                details.append({"model": model, "arm": arm, "noise": noise,
                                "mean_cmer": statistics.mean(float(r["cmer"]) for r in part),
                                "median_cmer": statistics.median(float(r["cmer"]) for r in part),
                                "mean_delta_noop": statistics.mean(float(r["cmer"]) - baseline[r["task_id"]] for r in part),
                                "mean_fixed_rate": statistics.mean(float(r["fixed_rate"]) for r in part),
                                "mean_broken_rate": statistics.mean(float(r["broken_rate"]) for r in part)})
        lines.extend([r"\bottomrule\end{tabular}\end{table}"])
        tables.extend(lines)
    (ROOT / "paper/data/all_arms.tex").write_text("\n".join(tables) + "\n", encoding="utf-8")
    (ROOT / "paper/data/noise_summary.json").write_text(json.dumps(details, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
