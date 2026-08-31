"""Create baseline hypothesis files using dummy correction strategies.

Usage:
    python lib/create_dummy_baselines.py <input1.jsonl> [<input2.jsonl> ...]
    python lib/create_dummy_baselines.py <input1.jsonl> [<input2.jsonl> ...] \
        --output-dir baselines.out \
        --swap-chars 0.01 0.05 --swap-words 0.01 --run-seeds

Creates one hypothesis file per strategy in the output directory.
Output filenames follow the submission naming convention:
    <strategy>_<benchmark-stem>_runN.jsonl
"""

import json
import math
import argparse
from pathlib import Path


def format_ratio_for_name(value: float) -> str:
    percent = value * 100
    if percent < 10 and float(percent).is_integer():
        return f"p0{int(percent)}"
    if float(percent).is_integer():
        return f"p{int(percent)}"
    return f"p{str(percent).rstrip('0').rstrip('.').replace('.', 'p')}"


class DummyCorrectPerfect:
    """Perfect baseline: copies the ground truth unchanged."""

    def __init__(self):
        self.name = "perfect"

    @staticmethod
    def source_text(record):
        return record["ground_truth"]["transcription_unit"]

    @staticmethod
    def correct_text(sentence, lang):
        return sentence


class DummyCorrectNoCorrection:
    """No-correction baseline: copies the OCR hypothesis unchanged."""

    def __init__(self):
        self.name = "baseline-no-correction"

    @staticmethod
    def source_text(record):
        return record["ocr_hypothesis"]["transcription_unit"]

    @staticmethod
    def correct_text(sentence, lang):
        return sentence


class DummyCorrectCharSwaps:
    """Swap a proportion of randomly chosen adjacent character pairs.

    The corrupted text is derived from the ground truth.
    A value of swap_ratio=0.01 means that approximately 1% of available
    non-overlapping adjacent character pairs in the text are swapped.
    """

    def __init__(self, swap_ratio: float, seed: int):
        from random import Random

        if not (0.0 <= swap_ratio <= 1.0):
            raise ValueError("--swap-chars values must be in the range [0, 1].")

        self.swap_ratio = swap_ratio
        self.rng = Random(seed)
        self.name = f"char-swaps-{format_ratio_for_name(swap_ratio)}"

    @staticmethod
    def source_text(record):
        return record["ground_truth"]["transcription_unit"]

    def correct_text(self, sentence, lang):
        if len(sentence) < 2 or self.swap_ratio <= 0.0:
            return sentence

        chars = list(sentence)

        # Non-overlapping adjacent pairs: (0,1), (2,3), (4,5), ...
        pair_starts = list(range(0, len(chars) - 1, 2))
        n_pairs = len(pair_starts)
        if n_pairs == 0:
            return sentence

        n_swaps = int(math.floor(n_pairs * self.swap_ratio))
        if n_swaps == 0 and self.swap_ratio > 0:
            n_swaps = 1
        n_swaps = min(n_swaps, n_pairs)

        chosen_starts = self.rng.sample(pair_starts, n_swaps)
        for i in chosen_starts:
            chars[i], chars[i + 1] = chars[i + 1], chars[i]

        return "".join(chars)


class DummyCorrectWordSwaps:
    """Swap a proportion of randomly chosen adjacent word pairs.

    The corrupted text is derived from the ground truth.
    A value of swap_ratio=0.01 means that approximately 1% of available
    non-overlapping adjacent word pairs in the text are swapped.
    """

    def __init__(self, swap_ratio: float, seed: int):
        from random import Random

        if not (0.0 <= swap_ratio <= 1.0):
            raise ValueError("--swap-words values must be in the range [0, 1].")

        self.swap_ratio = swap_ratio
        self.rng = Random(seed)
        self.name = f"word-swaps-{format_ratio_for_name(swap_ratio)}"

    @staticmethod
    def source_text(record):
        return record["ground_truth"]["transcription_unit"]

    def correct_text(self, sentence, lang):
        words = sentence.split()
        if len(words) < 2 or self.swap_ratio <= 0.0:
            return sentence

        # Non-overlapping adjacent pairs: (0,1), (2,3), (4,5), ...
        pair_starts = list(range(0, len(words) - 1, 2))
        n_pairs = len(pair_starts)
        if n_pairs == 0:
            return sentence

        n_swaps = int(math.floor(n_pairs * self.swap_ratio))
        if n_swaps == 0 and self.swap_ratio > 0:
            n_swaps = 1
        n_swaps = min(n_swaps, n_pairs)

        chosen_starts = self.rng.sample(pair_starts, n_swaps)
        for i in chosen_starts:
            words[i], words[i + 1] = words[i + 1], words[i]

        return " ".join(words)


def create_baseline(input_path, output_path, strategy):
    """Apply a correction strategy to each record and write the result."""
    print(f"  Reading from: {input_path}")
    count = 0
    with open(input_path, "r", encoding="utf-8") as fin, open(
        output_path, "w", encoding="utf-8"
    ) as fout:
        print(f"  Writing to:   {output_path}")
        for line in fin:
            if not line.strip():
                continue

            record = json.loads(line)
            lang = record["document_metadata"].get("language", "unknown")
            source_text = strategy.source_text(record)

            record.setdefault("ocr_postcorrection_output", {})["transcription_unit"] = (
                strategy.correct_text(source_text, lang)
            )
            fout.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1

    return count


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create dummy baseline hypothesis files."
    )
    parser.add_argument(
        "input_files",
        nargs="+",
        help="One or more input JSONL files to process in order.",
    )
    parser.add_argument(
        "--output-dir",
        default="baselines.out",
        help="Output directory for generated baseline files (default: baselines.out).",
    )
    parser.add_argument(
        "--swap-chars",
        type=float,
        nargs="+",
        default=[],
        help=(
            "One or more proportions of non-overlapping adjacent character pairs "
            "to swap in the ground-truth text, e.g. --swap-chars 0.05 0.1"
        ),
    )
    parser.add_argument(
        "--swap-words",
        type=float,
        nargs="+",
        default=[],
        help=(
            "One or more proportions of non-overlapping adjacent word pairs "
            "to swap in the ground-truth text, e.g. --swap-words 0.05 0.1"
        ),
    )
    parser.add_argument(
        "--run-seeds",
        action="store_true",
        help=(
            "Generate run1, run2, and run3 for all swap-based strategies. "
            "The run number determines the random seed: run1 -> seed 1, "
            "run2 -> seed 2, run3 -> seed 3. Fixed strategies are written only as run1."
        ),
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=["perfect", "baseline-no-correction", "char-swaps", "word-swaps"],
        default=None,
        help=(
            "Specific strategies to generate. If not specified, generates all "
            "configured strategies based on other flags. Choices: perfect, "
            "baseline-no-correction, char-swaps, word-swaps."
        ),
    )
    return parser.parse_args()


def make_run_specs(use_run_seeds: bool):
    if use_run_seeds:
        return [("run1", 1), ("run2", 2), ("run3", 3)]
    return [("run1", 1)]


def main():
    args = parse_args()

    input_paths = [Path(p) for p in args.input_files]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_specs = make_run_specs(args.run_seeds)

    # Determine which strategies to generate
    strategies_filter = set(args.strategies) if args.strategies else None

    for input_path in input_paths:
        outputs = []

        # Fixed baselines: only run1
        if strategies_filter is None or "perfect" in strategies_filter:
            outputs.append((DummyCorrectPerfect(), "run1"))
        if strategies_filter is None or "baseline-no-correction" in strategies_filter:
            outputs.append((DummyCorrectNoCorrection(), "run1"))

        if strategies_filter is None or "char-swaps" in strategies_filter:
            for ratio in args.swap_chars:
                for run_name, seed in run_specs:
                    outputs.append((DummyCorrectCharSwaps(ratio, seed=seed), run_name))

        if strategies_filter is None or "word-swaps" in strategies_filter:
            for ratio in args.swap_words:
                for run_name, seed in run_specs:
                    outputs.append((DummyCorrectWordSwaps(ratio, seed=seed), run_name))

        for strategy, run_name in outputs:
            # Insert "masked-" before "test" in the stem
            modified_stem = input_path.stem.replace("_test_", "_masked-test_")
            output_path = (
                output_dir / f"{strategy.name}_{modified_stem}_{run_name}.jsonl"
            )
            count = create_baseline(input_path, output_path, strategy)
            print(
                f"[{strategy.name}/{run_name}] Wrote {count} records to {output_path}"
            )


if __name__ == "__main__":
    main()
