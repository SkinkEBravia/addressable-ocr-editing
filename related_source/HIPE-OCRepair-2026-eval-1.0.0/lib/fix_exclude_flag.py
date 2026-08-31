#!/usr/bin/env python3
"""Fix exclude_from_icdar_evaluation flag based on publication titles.

Reads JSONL reference data and sets ground_truth.exclude_from_icdar_evaluation
to true for documents matching the specified publication titles, false otherwise.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    """Load records from a JSONL file."""
    records = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"Error at line {i}: {exc}", file=sys.stderr)
                sys.exit(1)
    return records


def write_jsonl(records: list[dict], path: Path) -> None:
    """Write records to a JSONL file."""
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def fix_exclude_flags(
    records: list[dict], titles: set[str], mode: str = "exclude"
) -> tuple[list[dict], int, int]:
    """Set exclude_from_icdar_evaluation based on publication titles.

    Args:
        records: List of document records
        titles: Set of publication titles
        mode: Either "exclude" (exclude listed titles) or "include" (include only listed titles)

    Returns:
        (modified_records, excluded_count, included_count)
    """
    excluded_count = 0
    included_count = 0
    modified_records = []

    for record in records:
        # Create a copy of the record to avoid modifying shared references
        record_copy = record.copy()
        metadata = record_copy.get("document_metadata", {})
        pub_title = metadata.get("publication_title", "")

        # Ensure ground_truth dict exists and make a copy
        if "ground_truth" not in record_copy:
            record_copy["ground_truth"] = {}
        else:
            # Make a copy of the ground_truth dict to avoid shared references
            record_copy["ground_truth"] = record_copy["ground_truth"].copy()

        # Set the exclude flag based on mode
        if mode == "exclude":
            should_exclude = pub_title in titles
        else:  # mode == "include"
            should_exclude = pub_title not in titles

        # Always set the flag explicitly
        record_copy["ground_truth"]["exclude_from_icdar_evaluation"] = should_exclude

        if should_exclude:
            excluded_count += 1
        else:
            included_count += 1
        
        modified_records.append(record_copy)

    return modified_records, excluded_count, included_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix exclude_from_icdar_evaluation flag based on publication titles."
    )
    parser.add_argument(
        "input_file",
        type=Path,
        help="Input JSONL file (e.g., data/reference/hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_test_de.jsonl)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output JSONL file (default: overwrite input file)",
    )
    
    # Create mutually exclusive group for exclude/include modes
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--exclude-titles",
        nargs="+",
        help="List of publication titles to exclude from ICDAR evaluation (all others included)",
    )
    mode_group.add_argument(
        "--include-titles",
        nargs="+",
        help="List of publication titles to include in ICDAR evaluation (all others excluded)",
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without modifying files",
    )

    args = parser.parse_args()

    if not args.input_file.is_file():
        print(f"Error: Input file not found: {args.input_file}", file=sys.stderr)
        sys.exit(1)

    # Load records
    print(f"Loading {args.input_file}...", file=sys.stderr)
    records = load_jsonl(args.input_file)
    print(f"Loaded {len(records)} records", file=sys.stderr)

    # Collect all publication titles from the data
    all_pub_titles = set()
    for record in records:
        metadata = record.get("document_metadata", {})
        pub_title = metadata.get("publication_title", "")
        if pub_title:
            all_pub_titles.add(pub_title)

    # Determine mode and titles
    if args.exclude_titles:
        mode = "exclude"
        titles = set(args.exclude_titles)
        print(f"Excluding documents with publication titles: {titles}", file=sys.stderr)
    else:
        mode = "include"
        titles = set(args.include_titles)
        print(f"Including only documents with publication titles: {titles}", file=sys.stderr)

    # Check for unmatched titles
    unmatched_titles = titles - all_pub_titles
    if unmatched_titles:
        print(f"\n[WARNING] The following titles were not found in the data:", file=sys.stderr)
        for title in sorted(unmatched_titles):
            print(f"  - {title}", file=sys.stderr)

    # Fix flags
    modified_records, excluded_count, included_count = fix_exclude_flags(
        records, titles, mode
    )

    print(f"\nResults:", file=sys.stderr)
    print(f"  Excluded (true):  {excluded_count}", file=sys.stderr)
    print(f"  Included (false): {included_count}", file=sys.stderr)

    # Generate markdown checkbox list with all publication titles
    pub_title_status = {}
    for record in modified_records:
        metadata = record.get("document_metadata", {})
        pub_title = metadata.get("publication_title", "")
        if pub_title:
            is_excluded = record["ground_truth"].get("exclude_from_icdar_evaluation", False)
            pub_title_status[pub_title] = is_excluded

    print(f"\nMarkdown checkbox list for {args.input_file}:", file=sys.stderr)
    for pub_title in sorted(all_pub_titles):
        checkbox = "[ ]" if pub_title_status.get(pub_title, False) else "[x]"
        print(f"- {checkbox} {pub_title}", file=sys.stderr)

    # Write output
    if args.dry_run:
        print("\n[DRY RUN] No files modified", file=sys.stderr)
    else:
        output_path = args.output if args.output else args.input_file
        
        # Create backup if overwriting the input file
        if output_path == args.input_file:
            backup_path = Path(str(output_path) + ".backup")
            shutil.copy2(output_path, backup_path)
            print(f"\nCreated backup: {backup_path}", file=sys.stderr)
        
        write_jsonl(modified_records, output_path)
        print(f"Wrote {len(modified_records)} records to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
