#!/usr/bin/env bash
# Script to exclude specific DTA publications from ICDAR evaluation
# By default, runs in dry-run mode (safe)
# Set DTA_NO_DRY_RUN=1 to make actual changes

# Determine dry-run flag based on environment variable
if [ -n "$DTA_NO_DRY_RUN" ]; then
  DRY_RUN_FLAG=""
  echo "DTA_NO_DRY_RUN is set - MAKING ACTUAL CHANGES"
else
  DRY_RUN_FLAG="--dry-run"
  echo "Running in dry-run mode (set DTA_NO_DRY_RUN=1 to make actual changes)"
fi

./lib/fix_exclude_flag.py data/reference/hipe-ocrepair-bench_v0.9_dta19-l2_v0.1_test_de.jsonl \
  --include-titles "1802-novalis_ofterdingen" "1815-hoffmann_elixiere01" "1826-eichendorff_taugenichts" \
  $DRY_RUN_FLAG

./lib/fix_exclude_flag.py data/reference/hipe-ocrepair-bench_v0.9_dta19-l1_v0.1_test_de.jsonl \
  --include-titles "1802-novalis_ofterdingen" "1815-hoffmann_elixiere01" "1826-eichendorff_taugenichts" \
  $DRY_RUN_FLAG

./lib/fix_exclude_flag.py data/reference/hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_test_de.jsonl \
  --include-titles "1802-novalis_ofterdingen" "1815-hoffmann_elixiere01" "1826-eichendorff_taugenichts" \
  $DRY_RUN_FLAG
