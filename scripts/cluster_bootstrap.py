"""Document-cluster bootstrap used for the arXiv manuscript."""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

DEFAULT_INPUT = Path(__file__).resolve().parents[1] / "paper" / "data" / "results.csv"
COMPARISONS = {
    "scope_v4": ("v4", "find-replace-blocked", "patch-find-replace"),
    "scope_v41": ("v41", "find-replace-blocked", "patch-find-replace"),
    "view_v4": ("v4", "find-replace", "find-replace-numkey"),
    "attention_v4": ("v4", "find-replace-numkey", "find-replace-blocked"),
    "scope_noatt_v4": ("v4", "find-replace-numkey", "patch-find-replace-noatt"),
    "scope_noatt_v41": ("v41", "find-replace-numkey", "patch-find-replace-noatt"),
    "view_v41": ("v41", "find-replace", "find-replace-numkey"),
    "stability_v4": ("v4", "patch-find-replace", "patch-find-replace-unstable"),
}


def load(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in ("cmer", "fixed_rate", "edit_spans"):
            row[key] = float(row[key])
    return rows


def percentile(values: list[float], q: float) -> float:
    values = sorted(values)
    return values[min(int(q * len(values)), len(values) - 1)]


def paired_cluster(rows, model: str, arm_a: str, arm_b: str, field: str,
                   resamples: int, seed: int):
    if resamples < 1:
        raise ValueError("resamples must be positive")
    selected = [r for r in rows if r["model"] == model and r["arm"] in (arm_a, arm_b)]
    by_task = {(r["task_id"], r["arm"]): r for r in selected}
    if len(by_task) != len(selected):
        raise ValueError("Duplicate task/arm rows")
    tasks = sorted({r["task_id"] for r in selected})
    if not tasks or any((t, arm) not in by_task for t in tasks for arm in (arm_a, arm_b)):
        raise ValueError("Paired arms must have the same nonempty task set")
    if any(by_task[t, arm_a]["source_document"] != by_task[t, arm_b]["source_document"] for t in tasks):
        raise ValueError("Paired task source documents differ")
    documents = sorted({r["source_document"] for r in selected})
    groups = [[t for t in tasks if by_task[(t, arm_a)]["source_document"] == d]
              for d in documents]
    differences = None if field == "p90" else [
        by_task[(t, arm_b)][field] - by_task[(t, arm_a)][field]
        for t in tasks
    ]
    rng = random.Random(seed)
    index = {t: i for i, t in enumerate(tasks)}
    estimates = []
    for _ in range(resamples):
        sampled = [task for _ in documents for task in rng.choice(groups)]
        if field == "p90":
            a = [by_task[(t, arm_a)]["cmer"] for t in sampled]
            b = [by_task[(t, arm_b)]["cmer"] for t in sampled]
            estimates.append(percentile(b, .9) - percentile(a, .9))
        else:
            estimates.append(sum(differences[index[t]] for t in sampled) / len(sampled))
    estimates.sort()
    observed = (sum(differences) / len(differences) if differences is not None else
                percentile([by_task[(t, arm_b)]["cmer"] for t in tasks], .9) -
                percentile([by_task[(t, arm_a)]["cmer"] for t in tasks], .9))
    return {
        "difference": observed,
        "ci95": [estimates[int(.025 * resamples)], estimates[min(int(.975 * resamples), resamples - 1)]],
        "n_tasks": len(tasks), "n_source_documents": len(documents),
        "resamples": resamples, "seed": seed,
        "model": model, "arm_a": arm_a, "arm_b": arm_b,
        "estimand": "P90(B)-P90(A)" if field == "p90" else "mean(B-A)",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--resamples", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    rows = load(args.input)
    output = {}
    for name, (model, arm_a, arm_b) in COMPARISONS.items():
        output[name] = {
            "cmer": paired_cluster(rows, model, arm_a, arm_b, "cmer", args.resamples, args.seed),
            "p90": paired_cluster(rows, model, arm_a, arm_b, "p90", args.resamples, args.seed),
            "fixed_rate": paired_cluster(rows, model, arm_a, arm_b, "fixed_rate", args.resamples, args.seed),
            "edit_spans": paired_cluster(rows, model, arm_a, arm_b, "edit_spans", args.resamples, args.seed),
        }
    text = json.dumps(output, indent=2)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
