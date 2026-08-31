#!/usr/bin/env python3
"""Export aligned OCR, ground truth, and correction texts for human diffing.

For a single hypothesis JSONL and its matching reference JSONL, this script writes
three multiline text files with identical record boundaries and ordering:

  <output-prefix>.orig.txt
  <output-prefix>.gth.txt
  <output-prefix>.cor.txt

Each transcription unit is preceded by a stable document header so normal diff
tools can align sections cleanly.
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from hipe_ocrepair_scorer import align_records, norm


def setup_logging(log_file: Path | None = None) -> None:
    handlers: list[logging.Handler] = []

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    handlers.append(console_handler)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )
        handlers.append(file_handler)

    logging.basicConfig(level=logging.DEBUG, handlers=handlers, force=True)


def load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logging.error("%s line %d: %s", path, i, exc)
                sys.exit(1)
    return records


def derive_reference_stem(hypothesis_path: Path) -> str:
    stem = hypothesis_path.stem
    stem = re.sub(r"_run\d+$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"^[^_]+_", "", stem)
    stem = re.sub(r"_masked-test_", "_test_", stem, flags=re.IGNORECASE)
    return stem


def filter_excluded_records(records: list[dict]) -> tuple[list[dict], int]:
    """Filter out records marked for exclusion from evaluation.
    
    Returns:
        (filtered_records, excluded_count)
    """
    filtered = []
    excluded_count = 0
    for record in records:
        is_excluded = record.get("ground_truth", {}).get(
            "exclude_from_icdar_evaluation", False
        )
        if not is_excluded:
            filtered.append(record)
        else:
            excluded_count += 1
    return filtered, excluded_count


def apply_normalizations(records: list[dict]) -> list[dict]:
    """Apply evaluator-style normalization to all transcription_unit fields."""
    normalized_records = []
    for record in records:
        normalized = record.copy()
        for channel_key in [
            "ocr_hypothesis",
            "ground_truth",
            "ocr_postcorrection_output",
        ]:
            if channel_key in normalized:
                channel = normalized[channel_key].copy()
                if "transcription_unit" in channel:
                    channel["transcription_unit"] = norm(
                        channel["transcription_unit"]
                    )
                normalized[channel_key] = channel
        normalized_records.append(normalized)
    return normalized_records


def build_record_block(document_id: str, text: str) -> str:
    return f"===== {document_id} =====\n{text}\n\n"


def write_channel(records: list[dict], channel_key: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for record in records:
            metadata = record.get("document_metadata", {})
            document_id = str(metadata.get("document_id", "UNKNOWN_DOCUMENT_ID"))
            channel = record.get(channel_key, {})
            text = channel.get("transcription_unit", "")
            if not isinstance(text, str):
                text = str(text)
            f.write(build_record_block(document_id, text))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export aligned OCR/reference/correction texts for human diffing."
    )
    parser.add_argument("--hypothesis", required=True, help="Path to hypothesis JSONL.")
    parser.add_argument(
        "--reference-dir", required=True, help="Directory with reference JSONL files."
    )
    parser.add_argument(
        "--output-prefix",
        required=True,
        help="Prefix for output files; writes .orig.txt, .gth.txt, and .cor.txt.",
    )
    parser.add_argument("--log-file", help="Path to write log output.")
    parser.add_argument(
        "--apply-normalizations",
        action="store_true",
        help=(
            "Apply evaluator-style text normalization before exporting (lowercase,"
            " punctuation removal, whitespace collapse)."
        ),
    )
    args = parser.parse_args()

    hyp_path = Path(args.hypothesis)
    ref_dir = Path(args.reference_dir)
    output_prefix = Path(args.output_prefix)
    log_file = Path(args.log_file) if args.log_file else None

    setup_logging(log_file)

    if not hyp_path.is_file():
        logging.error("Hypothesis file not found: %s", hyp_path)
        sys.exit(1)

    ref_stem = derive_reference_stem(hyp_path)
    ref_path = ref_dir / f"{ref_stem}.jsonl"
    if not ref_path.is_file():
        logging.error("Reference file not found: %s", ref_path)
        sys.exit(1)

    logging.info("Exporting text views: %s <-> %s", hyp_path.name, ref_path.name)

    ref_records = load_jsonl(ref_path)
    hyp_records = load_jsonl(hyp_path)
    merged = align_records(ref_records, hyp_records)
    if not merged:
        logging.error("No valid records after alignment for %s", hyp_path.name)
        sys.exit(1)

    logging.debug("Aligned %d records", len(merged))

    # Filter out excluded records (e.g., DTA records marked for exclusion)
    merged, excluded_count = filter_excluded_records(merged)
    if excluded_count > 0:
        logging.info("Excluded %d records marked with exclude_from_icdar_evaluation", excluded_count)
    logging.debug("Retained %d records after filtering", len(merged))

    if not merged:
        logging.error("No records remaining after filtering excluded records")
        sys.exit(1)

    if args.apply_normalizations:
        logging.info("Applied evaluator-style normalizations to exported text views")
        merged = apply_normalizations(merged)

    orig_path = Path(f"{output_prefix}.orig.txt")
    gth_path = Path(f"{output_prefix}.gth.txt")
    cor_path = Path(f"{output_prefix}.cor.txt")

    write_channel(merged, "ocr_hypothesis", orig_path)
    write_channel(merged, "ground_truth", gth_path)
    write_channel(merged, "ocr_postcorrection_output", cor_path)

    logging.info("Wrote %s", orig_path)
    logging.info("Wrote %s", gth_path)
    logging.info("Wrote %s", cor_path)
    if log_file:
        logging.info("Log written to: %s", log_file)


if __name__ == "__main__":
    main()
