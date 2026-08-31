# HIPE-OCRepair 2026 - Maintainer Summary

This file is now intentionally short.

Most operational and user-facing documentation lives in README.md.
This summary only keeps high-value maintainer context that is easy to lose in longer docs.

## Why Keep This File

- README.md is the canonical guide for setup, submission format, metrics, and rankings.
- This file tracks evaluator-level caveats and release checks.
- Keeping a short summary is useful for organizers; keeping the previous long version was redundant.

## Current Evaluation Policy (Condensed)

- Primary ranking metric: cmer_micro (lower is better).
- Secondary ranking metric: pref_score_cmer_macro (higher is better).
- Official overall score is an external weighted mean across 8 official test cells.
- DTA cells (dta19-l0, dta19-l1, dta19-l2) each use weight 1/3; other official cells use weight 1.
- impresso-nzz and overproof-combined are not part of official shared-task ranking.

## Documentation Hygiene Rule

When README and this file overlap, update README and keep this file minimal.
Target length for this file: one page.

Last reviewed: 2026-04-20
