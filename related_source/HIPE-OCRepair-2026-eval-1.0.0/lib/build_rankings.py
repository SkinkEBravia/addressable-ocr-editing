#!/usr/bin/env python3
"""Build TSV ranking files from per-run score JSON files.

Reads results/per-run/*.json, groups by (dataset, split, language),
sorts by cmer_micro ascending (lower is better), and writes one TSV
per group to results/system-rankings/.

Also produces per-split weighted rankings:
  ranking-overall-<split>-weighted.tsv
  ranking-language-<lang>-<split>-weighted.tsv

Weighting scheme (loaded from --competition-config):
  - Non-DTA test sets: weight = 1
  - DTA test sets (dta19-l0, dta19-l1, dta19-l2): weight = 1/3 each
    so that the three DTA parts together contribute as one dataset.

Primary metric:   weighted mean of per-test-set cmer_micro
Secondary metric: weighted mean of per-test-set pref_cmer_macro
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# Parses hypothesis stem:
# team1_hipe-ocrepair-bench_v0.9_impresso-snippets_dev_de_run1
# team1_hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_masked-test-unmatched_de_run1
HYPO_PATTERN = re.compile(
    r"^(?P<teamname>[^_]+)_"
    r"hipe-ocrepair-bench_(?P<version>[^_]+)_"
    r"(?P<dataset>.+)_"
    r"(?P<split>train|dev|test|masked-test)_"
    r"(?P<language>[a-z]{2})_"
    r"(?P<run>run\d+)$",
    re.IGNORECASE,
)


def parse_hypothesis_stem(stem: str) -> dict | None:
    m = HYPO_PATTERN.match(stem)
    if not m:
        return None
    meta = m.groupdict()
    # Normalize masked-test to test since they use the same reference files
    if meta["split"].lower() == "masked-test":
        meta["split"] = "test"
    return meta


def extract_metrics(averaged_scores: dict) -> dict:
    def get(key):
        v = averaged_scores.get(key, [None, None, None])
        return v[0], v[1], v[2]

    cm, cm_lo, cm_hi = get("cmer_macro")
    pref, pref_lo, pref_hi = get("pref_score_cmer_macro")
    cmi, cmi_lo, cmi_hi = get("cmer_micro")
    wm = averaged_scores.get("wmer_macro", [None])[0]

    return {
        "cmer_macro": cm,
        "cmer_macro_lo": cm_lo,
        "cmer_macro_hi": cm_hi,
        "pref_cmer_macro": pref,
        "pref_cmer_macro_lo": pref_lo,
        "pref_cmer_macro_hi": pref_hi,
        "cmer_micro": cmi,
        "cmer_micro_lo": cmi_lo,
        "cmer_micro_hi": cmi_hi,
        "wmer_macro": wm,
    }


def weighted_mean(value_weight_pairs) -> float | None:
    """Weighted mean over (value, weight) pairs; None values are skipped."""
    pairs = [(v, w) for v, w in value_weight_pairs if v is not None]
    if not pairs:
        return None
    total_w = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total_w


def round_row(row: dict, decimals: int = 4) -> dict:
    """Round all numeric values in a row dict to specified decimal places."""
    rounded = {}
    for key, value in row.items():
        if isinstance(value, float):
            rounded[key] = round(value, decimals)
        else:
            rounded[key] = value
    return rounded


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build TSV ranking files from per-run score JSONs."
    )
    parser.add_argument(
        "--per-run-dir", required=True, help="Directory with per-run JSON files."
    )
    parser.add_argument(
        "--output-dir", required=True, help="Directory to write ranking TSV files."
    )
    parser.add_argument(
        "--competition-config",
        default=None,
        help=(
            "JSON file listing competition cells with weights. If omitted, all datasets"
            " are included."
        ),
    )
    args = parser.parse_args()

    per_run_dir = Path(args.per_run_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    competition_cells: dict[tuple[str, str], float] = {}
    if args.competition_config:
        with open(args.competition_config, encoding="utf-8") as f:
            cfg = json.load(f)
        competition_cells = {(c["dataset"], c["language"]): c["weight"] for c in cfg}

    json_files = sorted(per_run_dir.glob("*.json"))
    if not json_files:
        print(f"[ERROR] No JSON files found in {per_run_dir}", file=sys.stderr)
        sys.exit(1)

    # Per-test-set groups: (dataset, split, language) -> list of row dicts
    groups: dict[tuple, list] = defaultdict(list)
    # Overall ranking: split -> {system_key -> {(dataset, language) -> metrics}}
    # Only competition cells are tracked (if config provided).
    overall: dict[str, dict] = defaultdict(lambda: defaultdict(dict))
    # Per-language ranking:
    # split -> language -> {system_key -> {(dataset, language) -> metrics}}
    per_language: dict[str, dict] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(dict))
    )

    for json_path in json_files:
        stem = json_path.stem
        meta = parse_hypothesis_stem(stem)
        if meta is None:
            print(
                f"[WARNING] Cannot parse filename: {stem}, skipping.", file=sys.stderr
            )
            continue

        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        metrics = extract_metrics(data.get("averaged_scores", {}))
        key = (meta["dataset"], meta["split"], meta["language"])
        groups[key].append({"system": stem, **metrics})

        system_key = (meta["teamname"], meta["version"], meta["run"])
        dataset_key = (meta["dataset"], meta["language"])
        if not competition_cells or dataset_key in competition_cells:
            overall[meta["split"]][system_key][dataset_key] = metrics
            per_language[meta["split"]][meta["language"]][system_key][
                dataset_key
            ] = metrics

    # --- Per-test-set TSVs ---
    FIELDNAMES = [
        "rank",
        "system",
        "cmer_micro",
        "cmer_micro_lo",
        "cmer_micro_hi",
        "pref_cmer_macro",
        "pref_cmer_macro_lo",
        "pref_cmer_macro_hi",
        "cmer_macro",
        "cmer_macro_lo",
        "cmer_macro_hi",
        "wmer_macro",
    ]

    for (dataset, split, language), rows in sorted(groups.items()):
        rows.sort(
            key=lambda r: (
                r["cmer_micro"] if r["cmer_micro"] is not None else float("inf"),
                -(
                    r["pref_cmer_macro"]
                    if r["pref_cmer_macro"] is not None
                    else float("-inf")
                ),
            )
        )

        tsv_name = f"ranking-{dataset}-{split}-{language}-cmer-micro.tsv"
        tsv_path = output_dir / tsv_name

        with open(tsv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=FIELDNAMES, delimiter="\t", extrasaction="ignore"
            )
            writer.writeheader()
            for rank, row in enumerate(rows, 1):
                writer.writerow(round_row({"rank": rank, **row}))

        print(f"Written: {tsv_path} ({len(rows)} systems)", file=sys.stderr)

    # --- Overall weighted ranking per split ---
    # Determine competition-cell (dataset, language) keys per split for n_total.
    all_test_sets: dict[str, set] = defaultdict(set)
    all_test_sets_by_language: dict[str, dict] = defaultdict(lambda: defaultdict(set))
    for dataset, split, language in groups:
        if not competition_cells or (dataset, language) in competition_cells:
            all_test_sets[split].add((dataset, language))
            all_test_sets_by_language[split][language].add((dataset, language))

    OVERALL_FIELDNAMES = [
        "rank",
        "system",
        "overall_cmer",
        "overall_cmer_lo",
        "overall_cmer_hi",
        "overall_pref",
        "overall_pref_lo",
        "overall_pref_hi",
        "n_test_sets",
        "n_total_test_sets",
    ]

    for split, systems in sorted(overall.items()):
        n_total = len(all_test_sets[split])
        rows = []
        for (teamname, version, run), dataset_metrics in systems.items():
            entries = [
                {
                    "cmi": m["cmer_micro"],
                    "cmi_lo": m["cmer_micro_lo"],
                    "cmi_hi": m["cmer_micro_hi"],
                    "pref": m["pref_cmer_macro"],
                    "pref_lo": m["pref_cmer_macro_lo"],
                    "pref_hi": m["pref_cmer_macro_hi"],
                    "w": (
                        competition_cells.get((d, l), 1.0) if competition_cells else 1.0
                    ),
                }
                for (d, l), m in sorted(dataset_metrics.items())
            ]
            rows.append(
                {
                    "system": f"{teamname}_hipe-ocrepair-bench_{version}_{run}",
                    "overall_cmer": weighted_mean((e["cmi"], e["w"]) for e in entries),
                    "overall_cmer_lo": weighted_mean(
                        (e["cmi_lo"], e["w"]) for e in entries
                    ),
                    "overall_cmer_hi": weighted_mean(
                        (e["cmi_hi"], e["w"]) for e in entries
                    ),
                    "overall_pref": weighted_mean((e["pref"], e["w"]) for e in entries),
                    "overall_pref_lo": weighted_mean(
                        (e["pref_lo"], e["w"]) for e in entries
                    ),
                    "overall_pref_hi": weighted_mean(
                        (e["pref_hi"], e["w"]) for e in entries
                    ),
                    "n_test_sets": len(dataset_metrics),
                    "n_total_test_sets": n_total,
                }
            )

        rows.sort(
            key=lambda r: (
                r["overall_cmer"] if r["overall_cmer"] is not None else float("inf"),
                -(
                    r["overall_pref"]
                    if r["overall_pref"] is not None
                    else float("-inf")
                ),
            )
        )

        tsv_name = f"ranking-overall-{split}-weighted.tsv"
        tsv_path = output_dir / tsv_name

        with open(tsv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=OVERALL_FIELDNAMES, delimiter="\t", extrasaction="ignore"
            )
            writer.writeheader()
            for rank, row in enumerate(rows, 1):
                writer.writerow(round_row({"rank": rank, **row}))

        print(
            f"Written: {tsv_path} ({len(rows)} systems, {n_total} test sets)",
            file=sys.stderr,
        )

    # --- Per-language weighted ranking per split ---
    LANG_FIELDNAMES = [
        "rank",
        "system",
        "language",
        "language_cmer",
        "language_cmer_lo",
        "language_cmer_hi",
        "language_pref",
        "language_pref_lo",
        "language_pref_hi",
        "n_test_sets",
        "n_total_test_sets",
    ]

    for split, lang_systems in sorted(per_language.items()):
        for language, systems in sorted(lang_systems.items()):
            n_total = len(all_test_sets_by_language[split][language])
            rows = []
            for (teamname, version, run), dataset_metrics in systems.items():
                entries = [
                    {
                        "cmi": m["cmer_micro"],
                        "cmi_lo": m["cmer_micro_lo"],
                        "cmi_hi": m["cmer_micro_hi"],
                        "pref": m["pref_cmer_macro"],
                        "pref_lo": m["pref_cmer_macro_lo"],
                        "pref_hi": m["pref_cmer_macro_hi"],
                        "w": (
                            competition_cells.get((d, l), 1.0)
                            if competition_cells
                            else 1.0
                        ),
                    }
                    for (d, l), m in sorted(dataset_metrics.items())
                ]
                rows.append(
                    {
                        "system": f"{teamname}_hipe-ocrepair-bench_{version}_{run}",
                        "language": language,
                        "language_cmer": weighted_mean(
                            (e["cmi"], e["w"]) for e in entries
                        ),
                        "language_cmer_lo": weighted_mean(
                            (e["cmi_lo"], e["w"]) for e in entries
                        ),
                        "language_cmer_hi": weighted_mean(
                            (e["cmi_hi"], e["w"]) for e in entries
                        ),
                        "language_pref": weighted_mean(
                            (e["pref"], e["w"]) for e in entries
                        ),
                        "language_pref_lo": weighted_mean(
                            (e["pref_lo"], e["w"]) for e in entries
                        ),
                        "language_pref_hi": weighted_mean(
                            (e["pref_hi"], e["w"]) for e in entries
                        ),
                        "n_test_sets": len(dataset_metrics),
                        "n_total_test_sets": n_total,
                    }
                )

            rows.sort(
                key=lambda r: (
                    (
                        r["language_cmer"]
                        if r["language_cmer"] is not None
                        else float("inf")
                    ),
                    -(
                        r["language_pref"]
                        if r["language_pref"] is not None
                        else float("-inf")
                    ),
                )
            )

            tsv_name = f"ranking-language-{language}-{split}-weighted.tsv"
            tsv_path = output_dir / tsv_name

            with open(tsv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=LANG_FIELDNAMES,
                    delimiter="\t",
                    extrasaction="ignore",
                )
                writer.writeheader()
                for rank, row in enumerate(rows, 1):
                    writer.writerow(round_row({"rank": rank, **row}))

            print(
                f"Written: {tsv_path} ({len(rows)} systems, {n_total} test sets)",
                file=sys.stderr,
            )


if __name__ == "__main__":
    main()
