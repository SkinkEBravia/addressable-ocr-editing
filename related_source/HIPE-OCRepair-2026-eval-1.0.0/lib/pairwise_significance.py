#!/usr/bin/env python3
"""
Pairwise significance testing using paired bootstrap.

Tests whether two systems are significantly different by resampling
the SAME documents for both systems and computing a 95% CI of the difference.
If the CI excludes zero, the systems are significantly different (α=0.05).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import numpy as np
from hipe_ocrepair_scorer import align_records, Evaluation


def derive_reference_stem(hypothesis_path: Path) -> str:
    """
    Derive reference filename stem from hypothesis filename.

    Example:
        bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_masked-test_de_run1.jsonl
        → hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_test_de.jsonl
    """
    parts = hypothesis_path.stem.split("_")
    # Skip team name, keep benchmark through language
    # Remove run suffix and any masked- prefix
    result_parts = []
    for part in parts[1:]:  # Skip team name
        if part.startswith("run"):
            break
        if part.startswith("masked-"):
            part = part.replace("masked-", "")
        result_parts.append(part)

    return "_".join(result_parts) + ".jsonl"


def impute_missing_corrections(
    records: List[Dict], verbose: bool = False
) -> List[Dict]:
    """
    Impute missing postcorrections with original OCR text.
    Handles None, "None", and empty string values in ocr_postcorrection_output.transcription_unit.
    """
    imputed_count = 0
    for rec in records:
        ocr_post = rec.get("ocr_postcorrection_output", {})
        post_text = ocr_post.get("transcription_unit")

        if post_text is None or post_text == "None" or post_text == "":
            # Copy OCR hypothesis to postcorrection
            ocr_hyp = rec.get("ocr_hypothesis", {})
            hyp_text = ocr_hyp.get("transcription_unit", "")

            # Ensure ocr_postcorrection_output exists
            if "ocr_postcorrection_output" not in rec:
                rec["ocr_postcorrection_output"] = {}

            rec["ocr_postcorrection_output"]["transcription_unit"] = hyp_text
            imputed_count += 1

    if verbose and imputed_count > 0:
        print(
            f"Imputed {imputed_count}/{len(records)} missing postcorrections",
            file=sys.stderr,
        )

    return records


def load_jsonl(path: Path) -> List[Dict]:
    """Load JSONL file into list of dicts."""
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def extract_per_document_scores(
    hypothesis_records: List[Dict], reference_records: List[Dict], verbose: bool = False
) -> Dict[str, np.ndarray]:
    """
    Extract per-document scores for a hypothesis-reference pair.

    Returns:
        Dictionary mapping metric names to numpy arrays of per-document scores.
        Metrics include: cMER, wMER, char_pref, word_pref
    """
    # Impute missing corrections
    hypothesis_records = impute_missing_corrections(hypothesis_records, verbose=verbose)

    # Align records (note: align_records expects (ref, hyp) order)
    aligned = align_records(reference_records, hypothesis_records)

    if verbose:
        print(f"Aligned {len(aligned)} document pairs", file=sys.stderr)

    # Create Evaluation instance
    ev = Evaluation(aligned)

    # Extract per-document scores using example_level_measures
    cmer_func = ev.example_level_measures["cmer"]
    wmer_func = ev.example_level_measures["wmer"]
    char_pref_func = ev.example_level_measures["pref_score_cmer"]
    word_pref_func = ev.example_level_measures["pref_score_wmer"]

    c_mer_scores = []
    w_mer_scores = []
    char_pref_scores = []
    word_pref_scores = []

    for doc in aligned:
        c_mer_scores.append(cmer_func(doc))
        w_mer_scores.append(wmer_func(doc))
        char_pref_scores.append(char_pref_func(doc))
        word_pref_scores.append(word_pref_func(doc))

    return {
        "cMER": np.array(c_mer_scores),
        "wMER": np.array(w_mer_scores),
        "char_pref": np.array(char_pref_scores),
        "word_pref": np.array(word_pref_scores),
    }


def paired_bootstrap_test(
    scores_a: np.ndarray,
    scores_b: np.ndarray,
    n_bootstrap: int = 10000,
    alpha: float = 0.05,
    random_seed: Optional[int] = None,
    lower_is_better: bool = False,
) -> Dict:
    """
    Paired bootstrap test for significance.

    Resamples the SAME document indices for both systems and computes
    the difference distribution. Tests if 95% CI excludes zero.

    Args:
        scores_a: Per-document scores for system A (numpy array)
        scores_b: Per-document scores for system B (numpy array)
        n_bootstrap: Number of bootstrap resamples (default: 10000)
        alpha: Significance level (default: 0.05 for 95% CI)
        random_seed: Random seed for reproducibility
        lower_is_better: If True, lower scores are better (e.g., for MER)

    Returns:
        Dictionary with:
            - mean_diff: Mean difference (A - B)
            - ci_lower: Lower bound of 95% CI
            - ci_upper: Upper bound of 95% CI
            - p_value: Two-tailed p-value
            - significant: Whether difference is significant
            - winner: Which system is better ("A", "B", or "tie")
    """
    if len(scores_a) != len(scores_b):
        raise ValueError(
            f"Score arrays must have same length: {len(scores_a)} vs {len(scores_b)}"
        )

    n_docs = len(scores_a)
    if random_seed is not None:
        np.random.seed(random_seed)

    # Observed difference
    observed_diff = np.mean(scores_a) - np.mean(scores_b)

    # Bootstrap resampling
    bootstrap_diffs = []
    for _ in range(n_bootstrap):
        # Resample SAME indices for both systems (paired)
        indices = np.random.choice(n_docs, size=n_docs, replace=True)
        boot_a = scores_a[indices]
        boot_b = scores_b[indices]
        boot_diff = np.mean(boot_a) - np.mean(boot_b)
        bootstrap_diffs.append(boot_diff)

    bootstrap_diffs = np.array(bootstrap_diffs)

    # Compute percentile CI
    ci_lower = np.percentile(bootstrap_diffs, 100 * alpha / 2)
    ci_upper = np.percentile(bootstrap_diffs, 100 * (1 - alpha / 2))

    # Two-tailed p-value: proportion of bootstrap samples with opposite sign
    if observed_diff >= 0:
        p_value = 2 * np.mean(bootstrap_diffs <= 0)
    else:
        p_value = 2 * np.mean(bootstrap_diffs >= 0)
    p_value = min(p_value, 1.0)  # Cap at 1.0

    # Determine significance and winner
    significant = not (ci_lower <= 0 <= ci_upper)
    if significant:
        if lower_is_better:
            # For MER: lower is better, so negative diff means A is better
            winner = "A" if observed_diff < 0 else "B"
        else:
            # For preference: higher is better, so positive diff means A is better
            winner = "A" if observed_diff > 0 else "B"
    else:
        winner = "tie"

    return {
        "mean_diff": observed_diff,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "p_value": p_value,
        "significant": significant,
        "winner": winner,
    }


def compare_systems(
    system_a_path: Path,
    system_b_path: Path,
    reference_dir: Path,
    n_bootstrap: int = 10000,
    random_seed: Optional[int] = None,
    verbose: bool = False,
) -> Dict:
    """
    Compare two systems using paired bootstrap testing.

    Returns:
        Dictionary with test results for each metric.
    """
    # Derive reference filename
    ref_stem_a = derive_reference_stem(system_a_path)
    ref_stem_b = derive_reference_stem(system_b_path)

    if ref_stem_a != ref_stem_b:
        raise ValueError(
            "Systems have different reference stems:\n"
            f"  System A: {ref_stem_a}\n"
            f"  System B: {ref_stem_b}"
        )

    ref_path = reference_dir / ref_stem_a
    if not ref_path.exists():
        raise FileNotFoundError(f"Reference file not found: {ref_path}")

    if verbose:
        print(f"Comparing systems:", file=sys.stderr)
        print(f"  A: {system_a_path.name}", file=sys.stderr)
        print(f"  B: {system_b_path.name}", file=sys.stderr)
        print(f"  Reference: {ref_path.name}", file=sys.stderr)

    # Load data
    hyp_a = load_jsonl(system_a_path)
    hyp_b = load_jsonl(system_b_path)
    ref = load_jsonl(ref_path)

    # Extract per-document scores
    scores_a = extract_per_document_scores(hyp_a, ref, verbose=verbose)
    scores_b = extract_per_document_scores(hyp_b, ref, verbose=verbose)

    # Run paired bootstrap for each metric
    results = {}
    metric_config = {
        "cMER": {"lower_is_better": True},
        "wMER": {"lower_is_better": True},
        "char_pref": {"lower_is_better": False},
        "word_pref": {"lower_is_better": False},
    }

    for metric, config in metric_config.items():
        if verbose:
            print(f"\nTesting {metric}...", file=sys.stderr)

        test_result = paired_bootstrap_test(
            scores_a[metric],
            scores_b[metric],
            n_bootstrap=n_bootstrap,
            random_seed=random_seed,
            lower_is_better=config["lower_is_better"],
        )
        results[metric] = test_result

        if verbose:
            sig_marker = "*" if test_result["significant"] else " "
            print(
                f"  Δ = {test_result['mean_diff']:+.4f} "
                f"[{test_result['ci_lower']:+.4f}, {test_result['ci_upper']:+.4f}] "
                f"p={test_result['p_value']:.4f} {sig_marker}",
                file=sys.stderr,
            )

    return results


def format_results(
    system_a_name: str, system_b_name: str, results: Dict, format_type: str = "text"
) -> str:
    """
    Format comparison results for display.

    Args:
        system_a_name: Name of system A
        system_b_name: Name of system B
        results: Test results from compare_systems()
        format_type: 'text', 'tsv', or 'json'
    """
    if format_type == "json":
        output = {
            "system_a": system_a_name,
            "system_b": system_b_name,
            "results": results,
        }
        return json.dumps(output, indent=2)

    elif format_type == "tsv":
        lines = []
        # Header
        lines.append(
            "\t".join(
                [
                    "system_a",
                    "system_b",
                    "metric",
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
        for metric in ["cMER", "wMER", "char_pref", "word_pref"]:
            r = results[metric]
            lines.append(
                "\t".join(
                    [
                        system_a_name,
                        system_b_name,
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

    else:  # text
        lines = []
        lines.append(f"Pairwise Comparison: {system_a_name} vs {system_b_name}")
        lines.append("=" * 80)

        for metric in ["cMER", "wMER", "char_pref", "word_pref"]:
            r = results[metric]
            lines.append(f"\n{metric}:")
            lines.append(f"  Mean difference (A - B): {r['mean_diff']:+.6f}")
            lines.append(f"  95% CI: [{r['ci_lower']:+.6f}, {r['ci_upper']:+.6f}]")
            lines.append(f"  p-value: {r['p_value']:.6f}")

            if r["significant"]:
                better_system = system_a_name if r["winner"] == "A" else system_b_name
                lines.append(
                    f"  *** SIGNIFICANT (α=0.05) - {better_system} is better ***"
                )
            else:
                lines.append(f"  Not significant (tie)")

        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Pairwise significance testing using paired bootstrap",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compare two systems
  python lib/pairwise_significance.py \\
    --system-a data/systems/bnf-mistral_*_run1.jsonl \\
    --system-b data/systems/l3i_*_run1.jsonl \\
    --reference-dir data/reference
  
  # Output as TSV
  python lib/pairwise_significance.py \\
    --system-a data/systems/system1_*.jsonl \\
    --system-b data/systems/system2_*.jsonl \\
    --reference-dir data/reference \\
    --format tsv > pairwise_results.tsv
        """,
    )

    parser.add_argument(
        "--system-a",
        type=Path,
        required=True,
        help="Path to system A hypothesis file (JSONL)",
    )
    parser.add_argument(
        "--system-b",
        type=Path,
        required=True,
        help="Path to system B hypothesis file (JSONL)",
    )
    parser.add_argument(
        "--reference-dir",
        type=Path,
        required=True,
        help="Directory containing reference files",
    )
    parser.add_argument(
        "--n-bootstrap",
        type=int,
        default=10000,
        help="Number of bootstrap resamples (default: 10000)",
    )
    parser.add_argument(
        "--random-seed", type=int, default=None, help="Random seed for reproducibility"
    )
    parser.add_argument(
        "--format",
        choices=["text", "tsv", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print progress messages to stderr"
    )

    args = parser.parse_args()

    # Validate inputs
    if not args.system_a.exists():
        print(f"Error: System A file not found: {args.system_a}", file=sys.stderr)
        sys.exit(1)
    if not args.system_b.exists():
        print(f"Error: System B file not found: {args.system_b}", file=sys.stderr)
        sys.exit(1)
    if not args.reference_dir.is_dir():
        print(
            f"Error: Reference directory not found: {args.reference_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Run comparison
    try:
        results = compare_systems(
            args.system_a,
            args.system_b,
            args.reference_dir,
            n_bootstrap=args.n_bootstrap,
            random_seed=args.random_seed,
            verbose=args.verbose,
        )

        # Format and print results
        output = format_results(
            args.system_a.stem, args.system_b.stem, results, format_type=args.format
        )
        print(output)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
