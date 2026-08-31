#!/usr/bin/env python3
"""
Fix BLOCR submission files where ocr_postcorrection_output is a string instead of an object.

Usage:
    python lib/fix_blocr_submissions.py data/systems/blocr_*.jsonl
    python lib/fix_blocr_submissions.py --dry-run data/systems/blocr_*.jsonl
"""

import argparse
import json
import sys
from pathlib import Path


def fix_record(record: dict) -> tuple[dict, bool]:
    """
    Fix a single record if ocr_postcorrection_output is a string.

    Returns:
        (fixed_record, was_fixed)
    """
    if "ocr_postcorrection_output" not in record:
        return record, False

    output = record["ocr_postcorrection_output"]

    # If it's already an object, no fix needed
    if isinstance(output, dict):
        return record, False

    # If it's a string, wrap it in the proper structure
    if isinstance(output, str):
        fixed_record = record.copy()
        fixed_record["ocr_postcorrection_output"] = {
            "transcription_unit": output,
            "num_tokens": -1,
            "num_chars": len(output),
            "quality_report": {},
        }
        return fixed_record, True

    # Unexpected type
    raise ValueError(
        f"Unexpected type for ocr_postcorrection_output: {type(output).__name__}"
    )


def fix_file(file_path: Path, dry_run: bool = False) -> dict:
    """
    Fix all records in a JSONL file.

    Returns:
        Statistics dictionary
    """
    stats = {"total_records": 0, "fixed_records": 0, "errors": 0}

    fixed_records = []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                if not line.strip():
                    continue

                stats["total_records"] += 1

                try:
                    record = json.loads(line)
                    fixed_record, was_fixed = fix_record(record)

                    if was_fixed:
                        stats["fixed_records"] += 1
                        print(f"  Line {line_num}: Fixed ocr_postcorrection_output")

                    fixed_records.append(fixed_record)

                except Exception as e:
                    stats["errors"] += 1
                    print(f"  Line {line_num}: ERROR - {e}", file=sys.stderr)
                    fixed_records.append(record if "record" in locals() else None)

        # Write back if not dry-run
        if not dry_run and stats["fixed_records"] > 0:
            backup_path = file_path.with_suffix(".jsonl.backup")
            file_path.rename(backup_path)
            print(f"  Created backup: {backup_path}")

            with open(file_path, "w", encoding="utf-8") as f:
                for record in fixed_records:
                    if record is not None:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")

            print(f"  Written fixed file: {file_path}")

    except Exception as e:
        print(f"ERROR reading {file_path}: {e}", file=sys.stderr)
        stats["errors"] += 1

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fix BLOCR submission files with string ocr_postcorrection_output"
    )
    parser.add_argument("files", nargs="+", type=Path, help="JSONL files to fix")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be fixed without modifying files",
    )

    args = parser.parse_args()

    total_stats = {
        "files_processed": 0,
        "total_records": 0,
        "fixed_records": 0,
        "errors": 0,
    }

    for file_path in args.files:
        if not file_path.exists():
            print(f"File not found: {file_path}", file=sys.stderr)
            continue

        print(f"\nProcessing: {file_path}")
        stats = fix_file(file_path, dry_run=args.dry_run)

        total_stats["files_processed"] += 1
        total_stats["total_records"] += stats["total_records"]
        total_stats["fixed_records"] += stats["fixed_records"]
        total_stats["errors"] += stats["errors"]

        print(f"  Records: {stats['total_records']}")
        print(f"  Fixed: {stats['fixed_records']}")
        if stats["errors"] > 0:
            print(f"  Errors: {stats['errors']}")

    print(f"\n{'='*60}")
    print(f"SUMMARY {'(DRY RUN)' if args.dry_run else ''}")
    print(f"{'='*60}")
    print(f"Files processed: {total_stats['files_processed']}")
    print(f"Total records: {total_stats['total_records']}")
    print(f"Fixed records: {total_stats['fixed_records']}")
    if total_stats["errors"] > 0:
        print(f"Errors: {total_stats['errors']}")

    if args.dry_run and total_stats["fixed_records"] > 0:
        print("\nRun without --dry-run to apply fixes.")

    return 1 if total_stats["errors"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
