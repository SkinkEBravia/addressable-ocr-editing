# Pairwise Significance Testing

## Overview

This directory contains tools for statistically rigorous pairwise comparison of OCR post-correction systems using **paired bootstrap testing**.

All `grep` examples in this document assume GNU grep with PCRE support (`grep -P`).

## The Problem: Why Per-System CIs Are Not Enough

The ranking tables show 95% confidence intervals (CIs) for each system, computed by bootstrapping that system's results independently. These CIs answer: _"How stable is this system's performance?"_

However, they **cannot** answer: _"Are systems A and B significantly different?"_

### Why Not?

- **Non-overlapping CIs** → Systems are definitely different (conservative test)
- **Overlapping CIs** → **Inconclusive** (could be different, could be tied)

This is because per-system CIs ignore the correlation between systems' performance on the same documents.

## The Solution: Paired Bootstrap Testing

**Paired bootstrap** resamples the **same documents** for both systems and computes the difference distribution. This directly tests: _"Is the difference between A and B larger than random noise?"_

### How It Works

1. For each bootstrap replicate:
   - Sample the **same** N documents with replacement
   - Compute metric for system A on those documents
   - Compute metric for system B on the **same** documents
   - Record difference: Δ = score_A - score_B

2. Build distribution of Δ across 10,000 replicates

3. Compute 95% CI of Δ:
   - If CI excludes 0 → **significantly different** (α=0.05)
   - If CI includes 0 → **not significantly different** (statistical tie)

4. Compute p-value: proportion of replicates with opposite sign

## Tools

### 1. `lib/pairwise_significance.py`

Compare two specific systems:

```bash
python lib/pairwise_significance.py \
  --system-a data/systems/bnf-mistral_*_run1.jsonl \
  --system-b data/systems/l3i_*_run1.jsonl \
  --reference-dir data/reference \
  --format text
```

**Outputs:**

- Text format: Human-readable summary
- TSV format: Machine-readable table (one row per metric)
- JSON format: Full structured results

**Use cases:**

- Compare two specific systems in detail
- Investigate surprising ranking results
- Validate manual observations

### 2. `lib/pairwise_overlaps.py`

Automatically identify and test all consecutive systems with overlapping CIs:

```bash
python lib/pairwise_overlaps.py \
  --rankings-dir results/system-rankings \
  --submissions-dir data/systems \
  --reference-dir data/reference \
  --metric cmer_micro \
  --output results/pairwise-overlaps.tsv \
  --verbose
```

**What it does:**

1. Reads ranking TSV files
2. Identifies consecutive systems with overlapping CIs on `--metric`
3. Runs paired bootstrap tests for each pair
4. Outputs TSV with all results

**Makefile targets:**

```bash
make pairwise-overlaps         # Real data
make pairwise-overlaps-dummy   # Dummy data
```

## Output Format: `pairwise-overlaps.tsv`

### Columns

| Column                               | Description                                                    |
| ------------------------------------ | -------------------------------------------------------------- |
| `test_set`                           | Test set identifier (e.g., `dta19-l0_v0.1_test_de`)            |
| `rank_a`, `rank_b`                   | Rankings of the two systems                                    |
| `system_a`, `system_b`               | System names (full submission filenames without .jsonl)        |
| `ranking_metric`                     | Metric used to identify overlap (e.g., `cmer_micro`)           |
| `ranking_score_a`, `ranking_score_b` | Point estimates from ranking table                             |
| `ranking_ci_lo_a`, `ranking_ci_hi_a` | System A's 95% CI from ranking                                 |
| `ranking_ci_lo_b`, `ranking_ci_hi_b` | System B's 95% CI from ranking                                 |
| `test_metric`                        | Metric being tested (`cMER`, `wMER`, `char_pref`, `word_pref`) |
| `mean_diff`                          | Mean difference: score_A - score_B                             |
| `ci_lower`, `ci_upper`               | 95% CI bounds of the difference                                |
| `p_value`                            | Two-tailed p-value                                             |
| `significant`                        | `yes` if significantly different (α=0.05), `no` if tied        |
| `winner`                             | `A`, `B`, or `tie`                                             |

### Interpretation

Each row represents one pairwise test. For a given system pair and test set:

- 4 rows are output (one per `test_metric`: cMER, wMER, char_pref, word_pref)
- All 4 tests use the same paired bootstrap resampling
- Different metrics may show different significance results

## Meaningful Use Cases

### 1. Validate Ranking Differences

**Question:** "System A is ranked higher than B, but are they really different?"

**Analysis:**

```bash
# Filter for a specific test set
grep -P '^dta19_l0_v0\.1_test_de\t.*\tcMER\t' results/pairwise-overlaps.tsv
```

**Interpretation:**

- `significant=yes` → Ranking difference is statistically supported
- `significant=no` → Systems are in a statistical tie (ranking might be arbitrary)

### 2. Identify Performance Tiers

**Question:** "Which groups of systems have indistinguishable performance?"

**Analysis:**

```bash
# Find all statistical ties
grep -P '\tno\ttie$' results/pairwise-overlaps.tsv | cut -f1,2,3,4,5 | sort | uniq
```

**Output:** Groups of consecutive systems that are statistically tied

**Use:** Present results as "tiers" rather than strict ranking:

- Tier 1: Systems 1-3 (statistically indistinguishable)
- Tier 2: Systems 4-5 (statistically indistinguishable)
- Tier 3: System 6 (significantly worse than Tier 2)

### 3. Detect Misleading Rankings

**Question:** "Where does the ranking give a false impression of difference?"

**Analysis:**

```bash
# Find cases where CIs overlap AND systems are tied
# (These are cases where the ranking looks close and IS close)
grep -P '\tno\ttie$' results/pairwise-overlaps.tsv
```

**Use:** Add footnotes to ranking tables noting which consecutive systems are not significantly different

### 4. Assess Stability Across Runs

**Question:** "Are different runs of the same system significantly different?"

**Analysis:**

```bash
# Compare run1 vs run2 for a specific team
python lib/pairwise_significance.py \
  --system-a data/systems/bnf-mistral_*_run1.jsonl \
  --system-b data/systems/bnf-mistral_*_run2.jsonl \
  --reference-dir data/reference
```

**Interpretation:**

- `significant=yes` → System is unstable (randomness affects results)
- `significant=no` → System is stable across runs

### 5. Metric Agreement

**Question:** "Do different metrics agree on which system is better?"

**Analysis:**

```bash
# Compare results for cMER vs wMER for a specific pair
grep -P 'system_a_name.*system_b_name' results/pairwise-overlaps.tsv | \
  grep -P '\t(cMER|wMER)\t'
```

**Interpretation:**

- If cMER says A > B but wMER says tie → Different granularities show different patterns
- If cMER and char_pref disagree → Character-level correction introduces new errors

### 6. Power Analysis

**Question:** "Do we have enough test documents to detect differences?"

**Analysis:**

```bash
# Count how many overlapping pairs are actually tied
total=$(grep -P '\tcMER\t' results/pairwise-overlaps.tsv | wc -l)
ties=$(grep -P '\tcMER\t.*\tno\ttie$' results/pairwise-overlaps.tsv | wc -l)
echo "Proportion of ties: $ties / $total"
```

**Interpretation:**

- High proportion of ties → May need more test data for finer-grained ranking
- Low proportion of ties → Ranking is well-supported by data

## Example Workflow

### Step 1: Generate rankings

```bash
make eval-full
```

### Step 2: Run pairwise overlap analysis

```bash
make pairwise-overlaps
```

### Step 3: Examine results

```bash
# How many system pairs have overlapping CIs?
wc -l results/pairwise-overlaps.tsv

# How many are actually significantly different?
grep -P '\tcMER\t.*\tyes\t[AB]$' results/pairwise-overlaps.tsv | wc -l

# Show all statistical ties
grep -P '\tcMER\t.*\tno\ttie$' results/pairwise-overlaps.tsv | \
  awk -F'\t' '{print $1, $2, $3, $4, $5, $17}'

# Find largest non-significant difference
grep -P '\tcMER\t.*\tno\ttie$' results/pairwise-overlaps.tsv | \
  sort -t$'\t' -k14 -rn | head -1
```

### Step 4: Update presentation

Add notes to ranking tables:

```
† Systems A and B are not significantly different (p=0.234)
†† Ranks 3-5 form a statistical tie
```

## Statistical Notes

### Multiple Testing Correction

When comparing many pairs, consider Bonferroni correction:

- Adjusted α = 0.05 / n_comparisons
- Example: 20 comparisons → use α = 0.0025 instead of 0.05

To apply:

```bash
# Filter for p < 0.0025 instead of p < 0.05
awk -F'\t' '$17 < 0.0025' results/pairwise-overlaps.tsv
```

### Effect Size

The `mean_diff` column shows the effect size (raw difference in metric values).

For cMER and wMER:

- Difference < 0.001 → Very small practical difference
- Difference > 0.01 → Moderate practical difference
- Difference > 0.05 → Large practical difference

For preference scores:

- Difference < 0.05 → Very small practical difference
- Difference > 0.2 → Moderate practical difference
- Difference > 0.5 → Large practical difference

A result can be:

- **Statistically significant** but **practically small** (large sample, tiny effect)
- **Statistically non-significant** but **practically large** (small sample, large effect)

Always consider both!

### Assumptions

Paired bootstrap assumes:

1. Documents are independent (reasonable for most test sets)
2. Documents are representative of future data
3. Systems are deterministic (or randomness is controlled)

Violations:

- If documents are heavily duplicated → Results may be overconfident
- If systems are highly random → Run multiple seeds and compare those too

## References

- Efron & Tibshirani (1993). _An Introduction to the Bootstrap_. Chapman & Hall.
- Berg-Kirkpatrick et al. (2012). "An Empirical Investigation of Statistical Significance in NLP". EMNLP.
- Dror et al. (2018). "The Hitchhiker's Guide to Testing Statistical Significance in Natural Language Processing". ACL.

## Quick Reference

| Task                         | Command                                                                                                    |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Compare two specific systems | `python lib/pairwise_significance.py --system-a A.jsonl --system-b B.jsonl --reference-dir data/reference` |
| Test all overlapping pairs   | `make pairwise-overlaps`                                                                                   |
| Find statistical ties        | `grep -P '\tno\ttie$' results/pairwise-overlaps.tsv`                                                       |
| Find largest effects         | `sort -t$'\t' -k14 -rn results/pairwise-overlaps.tsv \| head`                                              |
| Export subset to analyze     | `grep -P '^dta19_l0_v0\.1_test_de\t' results/pairwise-overlaps.tsv > dta19-l0-pairs.tsv`                   |
