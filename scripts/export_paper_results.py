"""Export non-text manuscript data from local reports; never copies API responses."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = {"v4": "", "v41": "v41-", "m3": "mm3-"}
ARMS = {
    "find-replace": "find_replace_anthropic_style",
    "find-replace-numkey": "find_replace_numkey",
    "find-replace-blocked": "find_replace_blocked",
    "patch-find-replace": "patch_find_replace",
    "patch-find-replace-noatt": "patch_find_replace_noatt",
    "patch-find-replace-unstable": "patch_find_replace_unstable",
    "rewrite": "rewrite_anthropic_style", "rewrite-numkey": "rewrite_numkey",
}
SCORES = ("cmer", "fixed_rate", "broken_rate", "halluc_ins", "edit_spans",
          "key_leak", "chunks_aligned", "n_chunks")


def export(runs, output):
    rows, sources = [], []
    for model, prefix in MODELS.items():
        baseline = None
        for arm, key in ARMS.items():
            run = prefix + "dta19-doc-1shot-" + arm
            path = runs / run / "report.json"
            raw = path.read_bytes()
            report = json.loads(raw)
            current_baseline = report["per_sample"]["noop"]
            assert len(current_baseline) == 33
            if baseline is not None:
                assert {t: v["score"] for t, v in baseline.items()} == {
                    t: v["score"] for t, v in current_baseline.items()}
            baseline = current_baseline
            sources.append({"run": run, "sha256": hashlib.sha256(raw).hexdigest(),
                            "models": report["models"], "toolsets": report["toolsets"]})
            arms = [(arm, report["per_sample"][key])]
            if arm == "find-replace":
                arms.insert(0, ("noop", baseline))
            for name, data in arms:
                assert set(data) == set(baseline)
                for task, entry in sorted(data.items()):
                    usage = entry.get("usage") or {}
                    rows.append({"model": model, "arm": name, "task_id": task,
                                 "source_document": task.split("/", 1)[1],
                                 "noise": task.split("/", 1)[0], "status": entry["status"],
                                 **{s: entry["score"][s] for s in SCORES},
                                 "output_tokens": usage.get("output_tokens", ""),
                                 "reasoning_tokens": usage.get("reasoning_tokens", "")})
    output.mkdir(parents=True, exist_ok=True)
    with (output / "results.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output / "provenance.json").write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(rows)} rows from {len(sources)} reports")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=ROOT / "runs")
    parser.add_argument("--output", type=Path, default=ROOT / "paper" / "data")
    args = parser.parse_args()
    export(args.runs, args.output)
