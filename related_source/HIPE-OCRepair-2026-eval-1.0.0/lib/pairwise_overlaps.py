#!/usr/bin/env python3
"""
Identify systems with overlapping CIs and run pairwise significance tests.

Reads ranking TSV files, identifies consecutive systems with overlapping
confidence intervals on the primary metric (cMER micro), and runs paired
bootstrap tests to determine if they are significantly different.

Outputs a TSV with pairwise comparison results.
"""

import argparse
import csv
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import subprocess
import json


def parse_ranking_file(tsv_path: Path) -> List[Dict]:
    """
    Parse a ranking TSV file.

    Returns:
        List of dictionaries with ranking data.
    """
    with open(tsv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)


def has_overlapping_ci(
    score_a: float,
    ci_lo_a: float,
    ci_hi_a: float,
    score_b: float,
    ci_lo_b: float,
    ci_hi_b: float,
) -> bool:
    """
    Check if two confidence intervals overlap.

    Returns True if the CIs overlap, False otherwise.
    """
    # CIs overlap if one's lower bound is less than the other's upper bound
    # and vice versa
    return not (ci_hi_a < ci_lo_b or ci_hi_b < ci_lo_a)


def derive_test_set_from_ranking_filename(filename: str) -> str:
    """
    Extract test set identifier from ranking filename.

    Example:
        ranking-dta19-l0_v0.1-test-de-cmer-micro.tsv
        → dta19-l0_v0.1_test_de
    """
    # Remove 'ranking-' prefix and '.tsv' suffix
    stem = filename.replace("ranking-", "").replace(".tsv", "")

    # Remove '-cmer-micro' suffix
    stem = stem.replace("-cmer-micro", "").replace("-cmer-macro", "")
    stem = stem.replace("-wmer-micro", "").replace("-wmer-macro", "")

    # Replace remaining '-' with '_' to match test set naming
    return stem.replace("-", "_")


def find_submission_file(
    system_name: str, submissions_dir: Path, test_set: str
) -> Optional[Path]:
    """
    Find the submission file for a system.

    The system name from ranking is the full submission filename without .jsonl
    """
    # System name is already the full stem
    submission_path = submissions_dir / f"{system_name}.jsonl"

    if submission_path.exists():
        return submission_path
    return None


def run_pairwise_test(
    system_a_path: Path,
    system_b_path: Path,
    reference_dir: Path,
    n_bootstrap: int = 10000,
) -> Dict:
    """
    Run pairwise significance test using lib/pairwise_significance.py

    Returns:
        Dictionary with test results.
    """
    cmd = [
        "venv/bin/python",
        "lib/pairwise_significance.py",
        "--system-a",
        str(system_a_path),
        "--system-b",
        str(system_b_path),
        "--reference-dir",
        str(reference_dir),
        "--n-bootstrap",
        str(n_bootstrap),
        "--format",
        "json",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def identify_overlaps(
    rankings_dir: Path,
    submissions_dir: Path,
    reference_dir: Path,
    metric: str = "cmer_micro",
    n_bootstrap: int = 10000,
    verbose: bool = False,
) -> List[Dict]:
    """
    Identify systems with overlapping CIs and test them.

    Only processes per-test-set rankings (e.g., ranking-dta19-l0_v0.1-test-de-cmer-micro.tsv).
    Skips aggregated rankings (ranking-language-*.tsv, ranking-overall-*.tsv) because these
    aggregate across multiple test sets and cannot be used for paired testing (no common set
    of documents to resample).

    Returns:
        List of comparison results.
    """
    results = []

    # Find all ranking files, excluding language-level and overall aggregates
    # (aggregated rankings combine multiple test sets and can't be used for pairwise testing)
    all_ranking_files = sorted(rankings_dir.glob("ranking-*.tsv"))
    ranking_files = [
        f
        for f in all_ranking_files
        if "language" not in f.name and "overall" not in f.name
    ]

    if verbose:
        skipped = len(all_ranking_files) - len(ranking_files)
        print(f"Found {len(ranking_files)} per-test-set ranking files", file=sys.stderr)
        if skipped > 0:
            print(
                f"Skipped {skipped} aggregated rankings (language/overall)",
                file=sys.stderr,
            )

    for ranking_file in ranking_files:
        if verbose:
            print(f"\nProcessing {ranking_file.name}...", file=sys.stderr)

        # Parse ranking
        rankings = parse_ranking_file(ranking_file)

        # Extract test set name
        test_set = derive_test_set_from_ranking_filename(ranking_file.name)

        # Check consecutive pairs for overlapping CIs
        for i in range(len(rankings) - 1):
            row_a = rankings[i]
            row_b = rankings[i + 1]

            # Skip if either system is incomplete (has "—" rank)
            if row_a.get("rank") == "—" or row_b.get("rank") == "—":
                continue

            # Get CI bounds for the metric
            score_a = float(row_a[metric])
            ci_lo_a = float(row_a[f"{metric}_lo"])
            ci_hi_a = float(row_a[f"{metric}_hi"])

            score_b = float(row_b[metric])
            ci_lo_b = float(row_b[f"{metric}_lo"])
            ci_hi_b = float(row_b[f"{metric}_hi"])

            # Check if CIs overlap
            if has_overlapping_ci(score_a, ci_lo_a, ci_hi_a, score_b, ci_lo_b, ci_hi_b):
                if verbose:
                    print(
                        f"  Overlap detected: rank {row_a['rank']} vs {row_b['rank']}",
                        file=sys.stderr,
                    )

                # Find submission files
                system_a = row_a["system"]
                system_b = row_b["system"]

                path_a = find_submission_file(system_a, submissions_dir, test_set)
                path_b = find_submission_file(system_b, submissions_dir, test_set)

                if path_a is None:
                    if verbose:
                        print(
                            f"    Warning: Could not find submission for {system_a}",
                            file=sys.stderr,
                        )
                    continue

                if path_b is None:
                    if verbose:
                        print(
                            f"    Warning: Could not find submission for {system_b}",
                            file=sys.stderr,
                        )
                    continue

                # Run pairwise test
                try:
                    if verbose:
                        print(f"    Running pairwise test...", file=sys.stderr)

                    test_results = run_pairwise_test(
                        path_a, path_b, reference_dir, n_bootstrap=n_bootstrap
                    )

                    # Add metadata and append to results
                    comparison = {
                        "test_set": test_set,
                        "rank_a": row_a["rank"],
                        "system_a": system_a,
                        "rank_b": row_b["rank"],
                        "system_b": system_b,
                        "ranking_metric": metric,
                        "ranking_score_a": score_a,
                        "ranking_ci_lo_a": ci_lo_a,
                        "ranking_ci_hi_a": ci_hi_a,
                        "ranking_score_b": score_b,
                        "ranking_ci_lo_b": ci_lo_b,
                        "ranking_ci_hi_b": ci_hi_b,
                        "results": test_results["results"],
                    }
                    results.append(comparison)

                    if verbose:
                        cmer_result = test_results["results"]["cMER"]
                        sig_marker = "*" if cmer_result["significant"] else " "
                        print(
                            f"    cMER: Δ={cmer_result['mean_diff']:+.6f} "
                            f"p={cmer_result['p_value']:.4f} {sig_marker}",
                            file=sys.stderr,
                        )

                except subprocess.CalledProcessError as e:
                    if verbose:
                        print(f"    Error running test: {e}", file=sys.stderr)
                    continue

    return results


def format_results_tsv(results: List[Dict]) -> str:
    """
    Format comparison results as TSV.

    Outputs one row per test set × system pair × metric.
    """
    lines = []

    # Header
    lines.append(
        "\t".join(
            [
                "test_set",
                "rank_a",
                "system_a",
                "rank_b",
                "system_b",
                "ranking_metric",
                "ranking_score_a",
                "ranking_ci_lo_a",
                "ranking_ci_hi_a",
                "ranking_score_b",
                "ranking_ci_lo_b",
                "ranking_ci_hi_b",
                "test_metric",
                "mean_diff",
                "ci_lower",
                "ci_upper",
                "p_value",
                "significant",
                "winner",
            ]
        )
    )

    # Data rows
    for comp in results:
        for metric in ["cMER", "wMER", "char_pref", "word_pref"]:
            r = comp["results"][metric]
            lines.append(
                "\t".join(
                    [
                        comp["test_set"],
                        str(comp["rank_a"]),
                        comp["system_a"],
                        str(comp["rank_b"]),
                        comp["system_b"],
                        comp["ranking_metric"],
                        f"{comp['ranking_score_a']:.6f}",
                        f"{comp['ranking_ci_lo_a']:.6f}",
                        f"{comp['ranking_ci_hi_a']:.6f}",
                        f"{comp['ranking_score_b']:.6f}",
                        f"{comp['ranking_ci_lo_b']:.6f}",
                        f"{comp['ranking_ci_hi_b']:.6f}",
                        metric,
                        f"{r['mean_diff']:.6f}",
                        f"{r['ci_lower']:.6f}",
                        f"{r['ci_upper']:.6f}",
                        f"{r['p_value']:.6f}",
                        "yes" if r["significant"] else "no",
                        r["winner"],
                    ]
                )
            )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Identify systems with overlapping CIs and run pairwise tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script:
1. Reads ranking TSV files from --rankings-dir
2. Identifies consecutive systems with overlapping CIs on --metric
3. Runs paired bootstrap tests using lib/pairwise_significance.py
4. Outputs TSV with comparison results

Output TSV columns:
- test_set: Test set identifier (e.g., dta19-l0_v0.1_test_de)
- rank_a, rank_b: Rankings of the two systems
- system_a, system_b: System names
- ranking_metric: Metric used for ranking (e.g., cmer_micro)
- ranking_score_*, ranking_ci_*: Point estimates and CIs from ranking
- test_metric: Metric being tested (cMER, wMER, char_pref, word_pref)
- mean_diff: Mean difference (A - B)
- ci_lower, ci_upper: 95% CI bounds of difference
- p_value: Two-tailed p-value
- significant: yes/no (α=0.05)
- winner: A, B, or tie

Meaningful uses:
- Identify ranking positions that are NOT statistically supported
- Find "performance tiers" (groups of systems that are statistically tied)
- Validate that ranking differences reflect real performance differences
- Detect cases where point estimates differ but statistical test shows tie
        """,
    )

    parser.add_argument(
        "--rankings-dir",
        type=Path,
        required=True,
        help="Directory containing ranking TSV files",
    )
    parser.add_argument(
        "--submissions-dir",
        type=Path,
        required=True,
        help="Directory containing submission JSONL files",
    )
    parser.add_argument(
        "--reference-dir",
        type=Path,
        required=True,
        help="Directory containing reference JSONL files",
    )
    parser.add_argument(
        "--metric",
        default="cmer_micro",
        choices=["cmer_micro", "cmer_macro", "wmer_micro", "wmer_macro"],
        help="Metric to check for overlapping CIs (default: cmer_micro)",
    )
    parser.add_argument(
        "--n-bootstrap",
        type=int,
        default=10000,
        help="Number of bootstrap resamples (default: 10000)",
    )
    parser.add_argument("--output", type=Path, help="Output TSV file (default: stdout)")
    parser.add_argument(
        "--verbose", action="store_true", help="Print progress messages to stderr"
    )

    args = parser.parse_args()

    # Validate inputs
    if not args.rankings_dir.is_dir():
        print(
            f"Error: Rankings directory not found: {args.rankings_dir}", file=sys.stderr
        )
        sys.exit(1)
    if not args.submissions_dir.is_dir():
        print(
            f"Error: Submissions directory not found: {args.submissions_dir}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not args.reference_dir.is_dir():
        print(
            f"Error: Reference directory not found: {args.reference_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Identify overlaps and run tests
    results = identify_overlaps(
        args.rankings_dir,
        args.submissions_dir,
        args.reference_dir,
        metric=args.metric,
        n_bootstrap=args.n_bootstrap,
        verbose=args.verbose,
    )

    if args.verbose:
        print(f"\nFound {len(results)} pairwise comparisons", file=sys.stderr)

    # Format and output
    output_tsv = format_results_tsv(results)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_tsv)
        if args.verbose:
            print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(output_tsv)


if __name__ == "__main__":
    main()
