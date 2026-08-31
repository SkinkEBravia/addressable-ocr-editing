# Quick Start: Pairwise Significance Testing

## TL;DR

```bash
# Run pairwise analysis on all systems with overlapping CIs
make pairwise-overlaps

# View results
head -20 results/pairwise-overlaps.tsv

# Find statistical ties
grep "significant\tno" results/pairwise-overlaps.tsv | cut -f1-5,13,17-19
```

## What This Does

**Problem**: Rankings show confidence intervals, but overlapping CIs don't tell you if systems are _significantly different_.

**Solution**: Paired bootstrap testing resamples the _same documents_ for both systems and tests if the difference is larger than random noise.

**Output**: TSV file showing which consecutive systems with overlapping CIs are actually significantly different vs. statistically tied.

## Quick Examples

### Example 1: Are ranks 2 and 3 really different?

```bash
# Method 1: Check in the pairwise-overlaps.tsv
grep "dta19-l0" results/pairwise-overlaps.tsv | grep "^2\t.*\t3\t" | grep "cMER"

# Method 2: Compare them directly
python lib/pairwise_significance.py \
  --system-a data/systems/rank2_system_*.jsonl \
  --system-b data/systems/rank3_system_*.jsonl \
  --reference-dir data/reference \
  --format text
```

**Interpretation**:

- `p_value < 0.05` and `significant=yes` → Ranking is justified
- `p_value > 0.05` and `significant=no` → Systems are tied (ranking is arbitrary)

### Example 2: Find all performance tiers

```bash
# Show all statistical ties
grep "cMER" results/pairwise-overlaps.tsv | \
  grep "significant\tno" | \
  awk -F'\t' '{print $1 " Ranks " $2 "-" $4 ": " $3 " ≈ " $5 " (p=" $17 ")"}'
```

**Example output**:

```
dta19-l0_v0.1_test_de Ranks 2-3: system_a ≈ system_b (p=0.234)
dta19-l0_v0.1_test_de Ranks 3-4: system_b ≈ system_c (p=0.456)
icdar2017_v1.1_test_en Ranks 1-2: best_a ≈ best_b (p=0.089)
```

**Interpretation**: Systems in consecutive tied pairs form a "tier"

### Example 3: Test system stability across runs

```bash
# Compare run1 vs run2 for same team
python lib/pairwise_significance.py \
  --system-a data/systems/bnf-mistral_*_run1.jsonl \
  --system-b data/systems/bnf-mistral_*_run2.jsonl \
  --reference-dir data/reference \
  --format text
```

**Interpretation**:

- `significant=no` → Good! System is stable
- `significant=yes` → Warning: Large variance between runs

## Output Columns Explained

The `results/pairwise-overlaps.tsv` file has these key columns:

| Column                 | Meaning                                      |
| ---------------------- | -------------------------------------------- |
| `test_set`             | Which test set (e.g., dta19-l0_v0.1_test_de) |
| `rank_a`, `rank_b`     | Ranking positions being compared             |
| `system_a`, `system_b` | System names                                 |
| `test_metric`          | cMER, wMER, char_pref, or word_pref          |
| `mean_diff`            | Mean difference (A - B)                      |
| `ci_lower`, `ci_upper` | 95% CI of difference                         |
| `p_value`              | Two-tailed p-value                           |
| `significant`          | **yes** if p < 0.05, **no** if p ≥ 0.05      |
| `winner`               | Which system is better (or "tie")            |

## Interpreting Results

### For cMER and wMER (lower is better):

```
mean_diff = -0.015, significant = yes, winner = A
```

→ System A has lower error by 0.015, difference is significant, **A is better**

```
mean_diff = +0.003, significant = no, winner = tie
```

→ System B has lower error by 0.003, but difference is NOT significant, **statistical tie**

### For char_pref and word_pref (higher is better):

```
mean_diff = +0.25, significant = yes, winner = A
```

→ System A has higher preference by 0.25, difference is significant, **A is better**

```
mean_diff = -0.05, significant = no, winner = tie
```

→ System B has higher preference by 0.05, but difference is NOT significant, **statistical tie**

## Common Analyses

### 1. How many ranking positions are actually significant?

```bash
# Total comparisons
total=$(grep "cMER" results/pairwise-overlaps.tsv | wc -l)

# Significant comparisons
sig=$(grep "cMER" results/pairwise-overlaps.tsv | grep "significant\tyes" | wc -l)

# Compute percentage
echo "Significant: $sig / $total = $(( sig * 100 / total ))%"
```

### 2. Show me the borderline cases (close to p=0.05)

```bash
grep "cMER" results/pairwise-overlaps.tsv | \
  awk -F'\t' '$17 > 0.03 && $17 < 0.07 {print $1 " " $3 " vs " $5 ": p=" $17}'
```

### 3. Find the largest effect that's NOT significant

```bash
grep "cMER" results/pairwise-overlaps.tsv | \
  grep "significant\tno" | \
  awk -F'\t' '{print sqrt($14*$14) " " $1 " " $3 " vs " $5}' | \
  sort -rn | head -1
```

### 4. Generate a summary per test set

```bash
for testset in $(cut -f1 results/pairwise-overlaps.tsv | sort -u | tail -n +2); do
    total=$(grep "^$testset\t" results/pairwise-overlaps.tsv | grep "cMER" | wc -l)
    sig=$(grep "^$testset\t" results/pairwise-overlaps.tsv | grep "cMER" | grep "significant\tyes" | wc -l)
    echo "$testset: $sig/$total significant differences"
done
```

## Updating Results Tables

Use the pairwise testing results to add footnotes to your ranking tables:

```markdown
| Rank | System | cMER (95% CI)        |
| ---- | ------ | -------------------- |
| 1    | Best   | 0.005 [0.004, 0.006] |
| 2†   | Good1  | 0.007 [0.005, 0.009] |
| 3†   | Good2  | 0.008 [0.006, 0.010] |
| 4    | OK     | 0.015 [0.012, 0.018] |

† Systems at ranks 2-3 are not significantly different (p=0.123)
```

## When to Use Each Tool

### Use `pairwise_significance.py` when:

- Comparing two specific systems in detail
- Investigating a surprising ranking result
- Testing stability across runs
- You want full statistical output for a single comparison

### Use `pairwise_overlaps.py` (via `make pairwise-overlaps`) when:

- Analyzing the entire ranking table
- Finding performance tiers systematically
- Generating data for publication
- You want to batch-process all overlapping pairs

## Statistical Notes

### p-value interpretation:

- `p < 0.001`: Very strong evidence of difference (★★★)
- `p < 0.01`: Strong evidence of difference (★★)
- `p < 0.05`: Evidence of difference (★)
- `p ≥ 0.05`: Insufficient evidence (statistical tie)

### Multiple testing:

If you're comparing N pairs, consider using stricter threshold:

```
α_corrected = 0.05 / N
```

Example: 20 comparisons → use p < 0.0025 instead of p < 0.05

### Effect size matters:

A difference can be:

- **Significant but tiny**: p=0.001, Δ=0.0001 (large sample, tiny effect)
- **Large but non-significant**: p=0.10, Δ=0.05 (small sample, large effect)

Always look at both `p_value` AND `mean_diff`!

## Troubleshooting

### Error: "Reference file not found"

The script derives the reference filename from the hypothesis filename. Ensure:

- Hypothesis: `system_hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_masked-test_de_run1.jsonl`
- Reference: `hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_test_de.jsonl`

### Error: "Score arrays must have same length"

The two systems processed different numbers of documents. This can happen if:

- One system has missing/invalid submissions for some documents
- The submissions are for different test sets

Solution: Ensure you're comparing systems for the same test set.

### Warning: "Imputed N missing postcorrections"

Some documents had missing or invalid postcorrection outputs. The script imputed them with the original OCR (i.e., "no correction"). This is expected behavior and matches the scorer's logic.

## Further Reading

- Full documentation: See [PAIRWISE_TESTING.md](PAIRWISE_TESTING.md)
- Implementation details: See [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)
- Statistical theory: Efron & Tibshirani (1993), "An Introduction to the Bootstrap"
