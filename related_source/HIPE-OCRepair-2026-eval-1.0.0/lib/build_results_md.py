#!/usr/bin/env python3
"""Build a HIPE-2022-style Markdown results document from TSV ranking files.

Reads results/system-rankings/ranking-*-cmer-micro.tsv and produces
HIPE_OCRepair_2026_evaluation_results.md.

TSV filename convention: ranking-<dataset>-<split>-<language>-cmer-micro.tsv
"""

import argparse
import csv
import json
import os
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

LANGUAGE_NAMES = {
    "de": "German",
    "fr": "French",
    "en": "English",
    "nl": "Dutch",
    "fi": "Finnish",
    "sv": "Swedish",
    "it": "Italian",
}


def load_teams(teams_json: Path) -> dict[str, str]:
    if teams_json.exists():
        with open(teams_json, encoding="utf-8") as f:
            return json.load(f)
    return {}


def fmt(val, precision: int = 4) -> str:
    if val is None or val == "":
        return "—"
    try:
        return f"{float(val):.{precision}f}"
    except (ValueError, TypeError):
        return str(val)


def parse_tsv_filename(name: str) -> dict | None:
    """Parse ranking-<dataset>-<split>-<language>-cmer-micro.tsv.

    Supports split names with hyphens such as masked-test and masked-test-unmatched.
    """
    m = re.match(
        r"^ranking-(?P<dataset>.+)-"
        r"(?P<split>train|dev|test|masked-test)-"
        r"(?P<language>[a-z]{2})-cmer-micro$",
        Path(name).stem,
    )
    if not m:
        return None
    return m.groupdict()


def parse_overall_tsv_filename(name: str) -> dict | None:
    """Parse ranking-overall-<split>-weighted.tsv."""
    m = re.match(
        r"^ranking-overall-" r"(?P<split>train|dev|test|masked-test)" r"-weighted$",
        Path(name).stem,
    )
    if not m:
        return None
    return {"split": m.group("split")}


def parse_language_tsv_filename(name: str) -> dict | None:
    """Parse ranking-language-<lang>-<split>-weighted.tsv."""
    m = re.match(
        r"^ranking-language-(?P<language>[^-]+)-"
        r"(?P<split>train|dev|test|masked-test)"
        r"-weighted$",
        Path(name).stem,
    )
    if not m:
        return None
    return {"language": m.group("language"), "split": m.group("split")}


def build_team_key_table(teams: dict) -> list[str]:
    lines = [
        "## Team key\n",
        "| Team ID | Affiliation |",
        "|---------|-------------|",
    ]
    for team_id, affiliation in sorted(teams.items()):
        lines.append(f"| {team_id} | {affiliation} |")
    return lines


def parse_system_name(system_name: str) -> dict[str, str] | None:
    """Parse system name into team, dataset descriptor, and run.

    Expected pattern:
    <team>_hipe-ocrepair-bench_<version>_<dataset_parts>_run<N>
    """
    marker = "_hipe-ocrepair-bench_"
    if marker not in system_name:
        return None

    team, tail = system_name.split(marker, 1)
    run_match = re.search(r"_run(?P<run>\d+)$", tail)
    if run_match is None:
        return None

    run = run_match.group("run")
    before_run = tail[: run_match.start()]

    # Remove leading benchmark version (e.g. v0.9_)
    before_run = re.sub(r"^v\d+(?:\.\d+)*_", "", before_run)

    return {
        "team": team,
        "dataset": before_run,
        "run": run,
        "system": system_name,
    }


def collect_submission_overview(
    dataset_groups: dict[str, list],
) -> dict[str, list[dict]]:
    """Collect unique submissions across all dataset ranking files by team."""
    seen_systems: set[str] = set()
    by_team: dict[str, list[dict]] = defaultdict(list)

    for entries in dataset_groups.values():
        for tsv_path, _meta in entries:
            with open(tsv_path, encoding="utf-8") as f:
                rows = list(csv.DictReader(f, delimiter="\t"))
            for row in rows:
                system = row.get("system", "").strip()
                if not system or system in seen_systems:
                    continue
                seen_systems.add(system)
                parsed = parse_system_name(system)
                if parsed is None:
                    by_team["(unparsed)"].append(
                        {
                            "team": "(unparsed)",
                            "dataset": "—",
                            "run": "—",
                            "system": system,
                        }
                    )
                else:
                    by_team[parsed["team"]].append(parsed)

    # Sort submissions within each team by dataset, then by run number
    for team in by_team:
        by_team[team] = sorted(
            by_team[team],
            key=lambda x: (
                x.get("dataset", ""),
                int(x.get("run", "0")) if str(x.get("run", "")).isdigit() else 0,
            ),
        )

    # Sort teams alphabetically (case-insensitive), with "(unparsed)" always last
    def team_sort_key(item):
        team_name = item[0]
        if team_name == "(unparsed)":
            return ("zzz", team_name)  # Sort unparsed to the end
        return ("", team_name.lower())

    return dict(sorted(by_team.items(), key=team_sort_key))


def build_submission_overview_table(by_team: dict[str, list[dict]]) -> list[str]:
    lines = [
        "## Submission overview\n",
        "| Team | Dataset | Run | System |",
        "|------|---------|-----|--------|",
    ]
    for team, submissions in by_team.items():
        for sub in submissions:
            lines.append(
                "| "
                f"{team} | {sub.get('dataset', '—')} | {sub.get('run', '—')}"
                f" | {sub.get('system', '—')} |"
            )
    return lines


def build_submission_counts_table(by_team: dict[str, list[dict]]) -> list[str]:
    """Build a table showing submission counts (runs) per team per dataset."""
    # Collect all unique datasets
    all_datasets = set()
    for submissions in by_team.values():
        for sub in submissions:
            dataset = sub.get("dataset", "")
            if dataset and dataset != "—":
                all_datasets.add(dataset)

    all_datasets = sorted(all_datasets)
    teams = list(by_team.keys())

    if not all_datasets or not teams:
        return []

    # Count submissions per team per dataset
    counts = {}
    for team, submissions in by_team.items():
        counts[team] = defaultdict(int)
        for sub in submissions:
            dataset = sub.get("dataset", "")
            if dataset and dataset != "—":
                counts[team][dataset] += 1

    # Build header with all teams
    lines = [
        "## Submission counts by team and dataset\n",
        "_Number of runs submitted per team for each dataset._\n",
        "| Dataset | " + " | ".join(teams) + " |",
        "|---------|" + "|".join(["-----"] * len(teams)) + "|",
    ]

    # Build rows for each dataset
    for dataset in all_datasets:
        team_counts = [str(counts[team].get(dataset, 0)) for team in teams]
        lines.append(f"| {dataset} | " + " | ".join(team_counts) + " |")

    return lines


def split_complete_incomplete(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split rows into complete (all test sets) and incomplete systems."""
    complete = []
    incomplete = []
    for row in rows:
        n = row.get("n_test_sets", "")
        n_total = row.get("n_total_test_sets", "")
        try:
            if n and n_total and int(n) == int(n_total):
                complete.append(row)
            else:
                incomplete.append(row)
        except (ValueError, TypeError):
            incomplete.append(row)
    return complete, incomplete


def build_ranking_table(rows: list[dict]) -> list[str]:
    header = (
        "| Rank | System | cMER micro ↓ | 95% CI | Pref cMER Macro ↑ | 95% CI |"
        " cMER macro | wMER macro |"
    )
    sep = (
        "|------|--------|--------------|--------|--------------|--------|"
        "------------|------------|"
    )
    lines = [header, sep]
    for row in rows:
        rank = row.get("rank", "")
        system = row.get("system", "")
        cmer_micro = fmt(row.get("cmer_micro"))
        ci = f"[{fmt(row.get('cmer_micro_lo'), 3)}, {fmt(row.get('cmer_micro_hi'), 3)}]"
        pref = fmt(row.get("pref_cmer_macro"))
        pref_ci = (
            f"[{fmt(row.get('pref_cmer_macro_lo'), 3)},"
            f" {fmt(row.get('pref_cmer_macro_hi'), 3)}]"
        )
        cmer_macro = fmt(row.get("cmer_macro"))
        wmer_macro = fmt(row.get("wmer_macro"))
        lines.append(
            f"| {rank} | {system} | {cmer_micro} | {ci} | {pref} | {pref_ci}"
            f" | {cmer_macro} | {wmer_macro} |"
        )
    return lines


def build_overall_ranking_table(rows: list[dict], rerank: bool = False) -> list[str]:
    header = (
        "| Rank | System | Overall cMER ↓ | 95% CI\u00b9 | Overall Pref Macro ↑ |"
        " 95% CI\u00b9 | Test sets |"
    )
    sep = (
        "|------|--------|----------------|---------|----------------------|"
        "---------|----------|"
    )
    lines = [header, sep]
    for row in rows:
        rank = "—" if rerank else row.get("rank", "")
        system = row.get("system", "")
        cmer = fmt(row.get("overall_cmer"))
        ci = (
            f"[{fmt(row.get('overall_cmer_lo'), 3)},"
            f" {fmt(row.get('overall_cmer_hi'), 3)}]"
        )
        pref = fmt(row.get("overall_pref"))
        pref_ci = (
            f"[{fmt(row.get('overall_pref_lo'), 3)},"
            f" {fmt(row.get('overall_pref_hi'), 3)}]"
        )
        n = row.get("n_test_sets", "")
        n_total = row.get("n_total_test_sets", "")
        lines.append(
            f"| {rank} | {system} | {cmer} | {ci} | {pref} | {pref_ci} |"
            f" {n}/{n_total} |"
        )
    return lines


def build_language_ranking_table(rows: list[dict], rerank: bool = False) -> list[str]:
    header = (
        "| Rank | System | Language cMER ↓ | 95% CI\u00b9 | Language Pref Macro ↑ |"
        " 95% CI\u00b9 | Test sets |"
    )
    sep = (
        "|------|--------|-----------------|---------|----------------------|"
        "---------|----------|"
    )
    lines = [header, sep]
    for row in rows:
        rank = "—" if rerank else row.get("rank", "")
        system = row.get("system", "")
        cmer = fmt(row.get("language_cmer"))
        ci = (
            f"[{fmt(row.get('language_cmer_lo'), 3)},"
            f" {fmt(row.get('language_cmer_hi'), 3)}]"
        )
        pref = fmt(row.get("language_pref"))
        pref_ci = (
            f"[{fmt(row.get('language_pref_lo'), 3)},"
            f" {fmt(row.get('language_pref_hi'), 3)}]"
        )
        n = row.get("n_test_sets", "")
        n_total = row.get("n_total_test_sets", "")
        lines.append(
            f"| {rank} | {system} | {cmer} | {ci} | {pref} | {pref_ci} |"
            f" {n}/{n_total} |"
        )
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Markdown results document from TSV ranking files."
    )
    parser.add_argument(
        "--rankings-dir", required=True, help="Directory with ranking TSV files."
    )
    parser.add_argument(
        "--teams-json", default="lib/teams.json", help="Path to teams JSON file."
    )
    parser.add_argument(
        "--output", required=True, help="Path to write Markdown results file."
    )
    parser.add_argument(
        "--scorer-version", default="0.9.0", help="Scorer version string."
    )
    parser.add_argument(
        "--data-version", default="v0.9", help="Benchmark version string."
    )
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        help="Evaluation date and time (YYYY-MM-DD HH:MM:SS).",
    )
    args = parser.parse_args()

    rankings_dir = Path(args.rankings_dir)
    output_path = Path(args.output)
    teams = load_teams(Path(args.teams_json))

    all_tsv_files = sorted(rankings_dir.glob("ranking-*.tsv"))
    if not all_tsv_files:
        print(f"[ERROR] No ranking TSV files found in {rankings_dir}")
        return

    # Separate overall-weighted, language-weighted, and per-test-set TSVs
    overall_tsvs: list[tuple] = []  # (tsv_path, meta)
    language_tsvs: list[tuple] = []  # (tsv_path, meta)
    dataset_groups: dict[str, list] = defaultdict(list)
    for tsv_path in all_tsv_files:
        overall_meta = parse_overall_tsv_filename(tsv_path.name)
        if overall_meta is not None:
            overall_tsvs.append((tsv_path, overall_meta))
            continue
        lang_meta = parse_language_tsv_filename(tsv_path.name)
        if lang_meta is not None:
            language_tsvs.append((tsv_path, lang_meta))
            continue
        meta = parse_tsv_filename(tsv_path.name)
        if meta is None:
            print(f"[WARNING] Cannot parse TSV filename: {tsv_path.name}, skipping.")
            continue
        dataset_groups[meta["dataset"]].append((tsv_path, meta))

    lines: list[str] = [
        "# HIPE-OCRepair 2026 – Evaluation Results\n",
        f"- **Generated**: {args.date}",
        f"- **Scorer**: hipe-ocrepair-scorer v{args.scorer_version}",
        f"- **Benchmark**: hipe-ocrepair-bench {args.data_version}",
        "",
        "System names follow the pattern:  ",
        (
            "`<teamname>_hipe-ocrepair-bench_<version>_<dataset>_<split>_"
            "<language>_run<N>`"
        ),
        "",
        (
            "For official submissions, `<split>` in system filenames is `masked-test`;"
            " reference files in `data/reference/` use `test`."
        ),
        "",
        (
            "**Primary metric**: overall micro-cMER — weighted mean of per-test-set"
            " cMER micro (`cmer_micro`) — **lower is better**  "
        ),
        (
            "**Secondary metric**: overall macro-preference — weighted mean of"
            " per-test-set preference score (`pref_cmer_macro`) —"
            " **higher is better**"
        ),
        "",
        (
            "**Weighting**: each non-DTA test set has weight\u00a01; each of the three"
            " DTA test sets (dta19-l0, dta19-l1, dta19-l2) has weight\u00a01/3,"
            " so that together they contribute as one dataset to the overall score."
            " These are design weights, not corpus-size weights."
        ),
        "",
    ]

    if teams:
        lines.extend(build_team_key_table(teams))
        lines.append("")

    submissions_by_team = collect_submission_overview(dataset_groups)
    if submissions_by_team:
        lines.extend(build_submission_overview_table(submissions_by_team))
        lines.append("")
        lines.extend(build_submission_counts_table(submissions_by_team))
        lines.append("")

    # --- Overall weighted rankings ---
    if overall_tsvs:
        lines.append("## Overall rankings\n")
        lines.append(
            "Scores are computed separately for each official test set. Overall"
            " benchmark scores are weighted averages over test sets, using the"
            " design weights described above."
        )
        lines.append("")
        lines.append(
            "\u00b9\u00a0CIs for overall scores are approximate (weighted average of"
            " per-test-set bootstrap CIs)."
        )
        lines.append("")
        for tsv_path, meta in sorted(overall_tsvs, key=lambda x: x[1]["split"]):
            assert meta is not None
            split = meta["split"]
            lines.append(f"### Overall — {split} split\n")
            with open(tsv_path, encoding="utf-8") as f:
                rows = list(csv.DictReader(f, delimiter="\t"))
            if rows:
                complete, incomplete = split_complete_incomplete(rows)
                if complete:
                    lines.extend(build_overall_ranking_table(complete, rerank=False))
                    lines.append("")
                if incomplete:
                    lines.append("#### Systems with incomplete test set coverage\n")
                    lines.append(
                        "_Systems that have not processed all test sets are shown "
                        "separately and not included in the official ranking._\n"
                    )
                    lines.extend(build_overall_ranking_table(incomplete, rerank=True))
                    lines.append("")
                tsv_rel = os.path.relpath(tsv_path, output_path.parent)
                lines.append(f"See [{tsv_path.name}]({tsv_rel}) for full details.\n")
            else:
                lines.append("_No results available._\n")

    # --- Per-language weighted rankings ---
    # Track systems with complete language coverage
    complete_systems_by_language = {}

    if language_tsvs:
        lines.append("## Per-language rankings\n")
        lines.append(
            "Per-language rankings are computed in the same way as the overall"
            " ranking, but restricted to the official test sets of the respective"
            " language."
        )
        lines.append("")
        lines.append(
            "\u00b9\u00a0CIs for language scores are approximate (weighted average of"
            " per-test-set bootstrap CIs)."
        )
        lines.append("")
        for tsv_path, meta in sorted(
            language_tsvs, key=lambda x: (x[1]["split"], x[1]["language"])
        ):
            assert meta is not None
            split = meta["split"]
            lang = meta["language"]
            lang_name = LANGUAGE_NAMES.get(lang, lang.upper())
            lines.append(f"### Language: {lang} ({lang_name}) — {split} split\n")
            with open(tsv_path, encoding="utf-8") as f:
                rows = list(csv.DictReader(f, delimiter="\t"))
            if rows:
                complete, incomplete = split_complete_incomplete(rows)

                # Track complete systems for this language
                complete_systems_by_language[lang] = {
                    row.get("system", "").split("_hipe-ocrepair-bench_")[0]
                    for row in complete
                }

                if complete:
                    lines.extend(build_language_ranking_table(complete, rerank=False))
                    lines.append("")
                if incomplete:
                    lines.append("#### Systems with incomplete test set coverage\n")
                    lines.append(
                        "_Systems that have not processed all test sets are shown "
                        "separately and not included in the official ranking._\n"
                    )
                    lines.extend(build_language_ranking_table(incomplete, rerank=True))
                    lines.append("")
                tsv_rel = os.path.relpath(tsv_path, output_path.parent)
                lines.append(f"See [{tsv_path.name}]({tsv_rel}) for full details.\n")
            else:
                lines.append("_No results available._\n")

    lines.append("## Results by dataset\n")

    for dataset in sorted(dataset_groups.keys()):
        lines.append(f"### Dataset: {dataset}\n")
        for tsv_path, meta in sorted(
            dataset_groups[dataset], key=lambda x: x[1]["language"]
        ):
            assert meta is not None
            lang = meta["language"]
            split = meta["split"]
            lang_name = LANGUAGE_NAMES.get(lang, lang.upper())
            lines.append(f"#### Language: {lang} ({lang_name}) — {split} split\n")
            lines.append(
                "cMER micro [`cmer_micro`] — ordered ascending (lower is better)\n"
            )

            with open(tsv_path, encoding="utf-8") as f:
                rows = list(csv.DictReader(f, delimiter="\t"))

            if rows:
                lines.extend(build_ranking_table(rows))
                lines.append("")
                tsv_rel = os.path.relpath(tsv_path, output_path.parent)
                lines.append(f"See [{tsv_path.name}]({tsv_rel}) for full details.\n")
            else:
                lines.append("_No results available._\n")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Written: {output_path}")


if __name__ == "__main__":
    main()
