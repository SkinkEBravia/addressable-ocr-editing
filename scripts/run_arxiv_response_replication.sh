#!/usr/bin/env bash
set -euo pipefail

# Run from /app in the container. Every output directory is new.
uv run python scripts/fetch_hipe_data.py

COMMON=(
  --dataset datasets/hipe_2026
  --toolsets noop,find_replace,find_replace_numkey,find_replace_blocked,patch_find_replace,patch_find_replace_noatt,patch_find_replace_unstable,rewrite,rewrite_numkey
  --split dev
  --loaders dta19-l0/de/doc,dta19-l1/de/doc,dta19-l2/de/doc
  --workers 11
  --no-stream
)

uv run python -m experiment "${COMMON[@]}" \
  --model configs/models/volc-deepseek-v4-flash-response-aligned.toml \
  --out runs/arxiv-response-v4-repeat

uv run python -m experiment "${COMMON[@]}" \
  --model configs/models/volc-deepseek-v4.1-flash-response-aligned.toml \
  --out runs/arxiv-response-v41-repeat

uv run python -m experiment "${COMMON[@]}" \
  --model configs/models/minimax-m3-response-aligned.toml \
  --out runs/arxiv-response-m3
