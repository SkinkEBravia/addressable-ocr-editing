#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

from importlib import resources
from jsonschema import ValidationError, validate  # type: ignore[import-untyped]


def load_schema(schema_path: Path) -> dict:
    with open(schema_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_file(file_path: Path, schema: dict) -> int:
    errors = 0
    with open(file_path, "r", encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"[JSON] {file_path} (line {line_num}): {exc}", file=sys.stderr)
                errors += 1
                continue

            try:
                validate(instance=record, schema=schema)
            except ValidationError as exc:
                print(
                    f"[SCHEMA] {file_path} (line {line_num}): {exc.message}",
                    file=sys.stderr,
                )
                errors += 1

    if errors == 0:
        print(f"[OK] {file_path}")
    else:
        print(f"[FAIL] {file_path}: {errors} error(s).", file=sys.stderr)

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate submission JSONL files against the HIPE-OCRepair schema."
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Directory containing submission JSONL files.",
    )
    parser.add_argument(
        "--schema",
        default=None,
        help="Optional path to a JSON schema file.",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.is_dir():
        print(f"[ERROR] Input directory not found: {input_dir}", file=sys.stderr)
        return 1

    if args.schema:
        schema_path = Path(args.schema)
    else:
        with resources.path(
            "hipe_ocrepair_scorer.data.schema", "hipe-ocrepair.schema.json"
        ) as builtin_path:
            schema_path = builtin_path

    if not schema_path.is_file():
        print(f"[ERROR] Schema file not found: {schema_path}", file=sys.stderr)
        return 1

    schema = load_schema(schema_path)
    files = sorted(input_dir.glob("*.jsonl"))
    if not files:
        print(f"[INFO] No JSONL files found in {input_dir}")
        return 0

    total_errors = 0
    for file_path in files:
        total_errors += validate_file(file_path, schema)

    if total_errors:
        print(
            f"[FAIL] Validation failed with {total_errors} total error(s).",
            file=sys.stderr,
        )
        return 1

    print(f"[OK] Validated {len(files)} file(s) with no schema errors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
