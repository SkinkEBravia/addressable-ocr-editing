# HIPE-OCRepair 2026 – Evaluation Results

- **Generated**: 2026-04-13 12:32:01
- **Scorer**: hipe-ocrepair-scorer v0.9.9
- **Benchmark**: hipe-ocrepair-bench v0.9

System names follow the pattern:  
`<teamname>_hipe-ocrepair-bench_<version>_<dataset>_<split>_<language>_run<N>`

For official submissions, `<split>` in system filenames is `masked-test`; reference files in `data/reference/` use `test`.

**Primary metric**: overall micro-cMER — weighted mean of per-test-set cMER micro (`cmer_micro`) — **lower is better**  
**Secondary metric**: overall macro-preference — weighted mean of per-test-set preference score (`pref_cmer_macro`) — **higher is better**

**Weighting**: each non-DTA test set has weight 1; each of the three DTA test sets (dta19-l0, dta19-l1, dta19-l2) has weight 1/3, so that together they contribute as one dataset to the overall score. These are design weights, not corpus-size weights.

## Team key

| Team ID | Affiliation |
|---------|-------------|
| Zakaria-ENSIAS | Zakaria-ENSIAS team |
| baseline-no-correction | Automatic Baseline that preserves text as is |
| blocr | blocr team |
| bnf-mistral | bnf-mistral team |
| l3i | l3i team |

## Submission overview

| Team | Dataset | Run | System |
|------|---------|-----|--------|
| baseline-no-correction | dta19-l0_v0.1_masked-test_de | 1 | baseline-no-correction_hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_masked-test_de_run1 |
| baseline-no-correction | dta19-l1_v0.1_masked-test_de | 1 | baseline-no-correction_hipe-ocrepair-bench_v0.9_dta19-l1_v0.1_masked-test_de_run1 |
| baseline-no-correction | dta19-l2_v0.1_masked-test_de | 1 | baseline-no-correction_hipe-ocrepair-bench_v0.9_dta19-l2_v0.1_masked-test_de_run1 |
| baseline-no-correction | icdar2017_v1.1_masked-test_en | 1 | baseline-no-correction_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_en_run1 |
| baseline-no-correction | icdar2017_v1.1_masked-test_fr | 1 | baseline-no-correction_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_fr_run1 |
| baseline-no-correction | impresso-snippets_v1.0_masked-test_de | 1 | baseline-no-correction_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_de_run1 |
| baseline-no-correction | impresso-snippets_v1.0_masked-test_en | 1 | baseline-no-correction_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_en_run1 |
| baseline-no-correction | impresso-snippets_v1.0_masked-test_fr | 1 | baseline-no-correction_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_fr_run1 |
| blocr | dta19-l0_v0.1_masked-test_de | 1 | blocr_hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_masked-test_de_run1 |
| blocr | dta19-l1_v0.1_masked-test_de | 1 | blocr_hipe-ocrepair-bench_v0.9_dta19-l1_v0.1_masked-test_de_run1 |
| blocr | dta19-l2_v0.1_masked-test_de | 1 | blocr_hipe-ocrepair-bench_v0.9_dta19-l2_v0.1_masked-test_de_run1 |
| blocr | icdar2017_v1.1_masked-test_en | 1 | blocr_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_en_run1 |
| blocr | icdar2017_v1.1_masked-test_fr | 1 | blocr_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_fr_run1 |
| blocr | impresso-snippets_v1.0_masked-test_de | 1 | blocr_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_de_run1 |
| blocr | impresso-snippets_v1.0_masked-test_en | 1 | blocr_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_en_run1 |
| blocr | impresso-snippets_v1.0_masked-test_fr | 1 | blocr_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_fr_run1 |
| bnf-mistral | dta19-l0_v0.1_masked-test_de | 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_masked-test_de_run1 |
| bnf-mistral | dta19-l0_v0.1_masked-test_de | 2 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_masked-test_de_run2 |
| bnf-mistral | dta19-l0_v0.1_masked-test_de | 3 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_masked-test_de_run3 |
| bnf-mistral | dta19-l1_v0.1_masked-test_de | 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l1_v0.1_masked-test_de_run1 |
| bnf-mistral | dta19-l1_v0.1_masked-test_de | 2 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l1_v0.1_masked-test_de_run2 |
| bnf-mistral | dta19-l1_v0.1_masked-test_de | 3 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l1_v0.1_masked-test_de_run3 |
| bnf-mistral | dta19-l2_v0.1_masked-test_de | 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l2_v0.1_masked-test_de_run1 |
| bnf-mistral | dta19-l2_v0.1_masked-test_de | 2 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l2_v0.1_masked-test_de_run2 |
| bnf-mistral | dta19-l2_v0.1_masked-test_de | 3 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l2_v0.1_masked-test_de_run3 |
| bnf-mistral | icdar2017_v1.1_masked-test_en | 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_en_run1 |
| bnf-mistral | icdar2017_v1.1_masked-test_en | 2 | bnf-mistral_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_en_run2 |
| bnf-mistral | icdar2017_v1.1_masked-test_en | 3 | bnf-mistral_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_en_run3 |
| bnf-mistral | icdar2017_v1.1_masked-test_fr | 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_fr_run1 |
| bnf-mistral | icdar2017_v1.1_masked-test_fr | 2 | bnf-mistral_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_fr_run2 |
| bnf-mistral | icdar2017_v1.1_masked-test_fr | 3 | bnf-mistral_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_fr_run3 |
| bnf-mistral | impresso-snippets_v1.0_masked-test_de | 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_de_run1 |
| bnf-mistral | impresso-snippets_v1.0_masked-test_de | 2 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_de_run2 |
| bnf-mistral | impresso-snippets_v1.0_masked-test_de | 3 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_de_run3 |
| bnf-mistral | impresso-snippets_v1.0_masked-test_en | 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_en_run1 |
| bnf-mistral | impresso-snippets_v1.0_masked-test_en | 2 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_en_run2 |
| bnf-mistral | impresso-snippets_v1.0_masked-test_en | 3 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_en_run3 |
| bnf-mistral | impresso-snippets_v1.0_masked-test_fr | 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_fr_run1 |
| bnf-mistral | impresso-snippets_v1.0_masked-test_fr | 2 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_fr_run2 |
| bnf-mistral | impresso-snippets_v1.0_masked-test_fr | 3 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_fr_run3 |
| l3i | dta19-l0_v0.1_masked-test_de | 1 | l3i_hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_masked-test_de_run1 |
| l3i | dta19-l1_v0.1_masked-test_de | 1 | l3i_hipe-ocrepair-bench_v0.9_dta19-l1_v0.1_masked-test_de_run1 |
| l3i | dta19-l2_v0.1_masked-test_de | 1 | l3i_hipe-ocrepair-bench_v0.9_dta19-l2_v0.1_masked-test_de_run1 |
| l3i | icdar2017_v1.1_masked-test_en | 1 | l3i_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_en_run1 |
| l3i | icdar2017_v1.1_masked-test_fr | 1 | l3i_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_fr_run1 |
| l3i | impresso-snippets_v1.0_masked-test_de | 1 | l3i_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_de_run1 |
| l3i | impresso-snippets_v1.0_masked-test_de | 2 | l3i_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_de_run2 |
| l3i | impresso-snippets_v1.0_masked-test_en | 1 | l3i_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_en_run1 |
| l3i | impresso-snippets_v1.0_masked-test_en | 2 | l3i_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_en_run2 |
| l3i | impresso-snippets_v1.0_masked-test_fr | 1 | l3i_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_fr_run1 |
| l3i | impresso-snippets_v1.0_masked-test_fr | 2 | l3i_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_fr_run2 |
| Zakaria-ENSIAS | dta19-l0_v0.1_masked-test_de | 1 | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_masked-test_de_run1 |
| Zakaria-ENSIAS | dta19-l1_v0.1_masked-test_de | 1 | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_dta19-l1_v0.1_masked-test_de_run1 |
| Zakaria-ENSIAS | icdar2017_v1.1_masked-test_en | 1 | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_en_run1 |
| Zakaria-ENSIAS | icdar2017_v1.1_masked-test_fr | 1 | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_fr_run1 |
| Zakaria-ENSIAS | impresso-snippets_v1.0_masked-test_de | 1 | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_de_run1 |
| Zakaria-ENSIAS | impresso-snippets_v1.0_masked-test_en | 1 | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_en_run1 |
| Zakaria-ENSIAS | impresso-snippets_v1.0_masked-test_fr | 1 | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_fr_run1 |

## Submission counts by team and dataset

_Number of runs submitted per team for each dataset._

| Dataset | baseline-no-correction | blocr | bnf-mistral | l3i | Zakaria-ENSIAS |
|---------|-----|-----|-----|-----|-----|
| dta19-l0_v0.1_masked-test_de | 1 | 1 | 3 | 1 | 1 |
| dta19-l1_v0.1_masked-test_de | 1 | 1 | 3 | 1 | 1 |
| dta19-l2_v0.1_masked-test_de | 1 | 1 | 3 | 1 | 0 |
| icdar2017_v1.1_masked-test_en | 1 | 1 | 3 | 1 | 1 |
| icdar2017_v1.1_masked-test_fr | 1 | 1 | 3 | 1 | 1 |
| impresso-snippets_v1.0_masked-test_de | 1 | 1 | 3 | 2 | 1 |
| impresso-snippets_v1.0_masked-test_en | 1 | 1 | 3 | 2 | 1 |
| impresso-snippets_v1.0_masked-test_fr | 1 | 1 | 3 | 2 | 1 |

## Overall rankings

Scores are computed separately for each official test set. Overall benchmark scores are weighted averages over test sets, using the design weights described above.

¹ CIs for overall scores are approximate (weighted average of per-test-set bootstrap CIs).

### Overall — test split

| Rank | System | Overall cMER ↓ | 95% CI¹ | Overall Pref Macro ↑ | 95% CI¹ | Test sets |
|------|--------|----------------|---------|----------------------|---------|----------|
| 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_run1 | 0.0050 | [0.004, 0.007] | 0.9000 | [0.835, 0.952] | 8/8 |
| 2 | bnf-mistral_hipe-ocrepair-bench_v0.9_run3 | 0.0071 | [0.005, 0.009] | 0.8737 | [0.803, 0.931] | 8/8 |
| 3 | bnf-mistral_hipe-ocrepair-bench_v0.9_run2 | 0.0090 | [0.007, 0.011] | 0.8739 | [0.791, 0.942] | 8/8 |
| 4 | blocr_hipe-ocrepair-bench_v0.9_run1 | 0.0106 | [0.008, 0.013] | 0.7028 | [0.574, 0.816] | 8/8 |
| 5 | l3i_hipe-ocrepair-bench_v0.9_run1 | 0.0176 | [0.014, 0.022] | 0.3591 | [0.229, 0.486] | 8/8 |
| 8 | baseline-no-correction_hipe-ocrepair-bench_v0.9_run1 | 0.0226 | [0.019, 0.026] | 0.0000 | [0.000, 0.000] | 8/8 |

#### Systems with incomplete test set coverage

_Systems that have not processed all test sets are shown separately and not included in the official ranking._

| Rank | System | Overall cMER ↓ | 95% CI¹ | Overall Pref Macro ↑ | 95% CI¹ | Test sets |
|------|--------|----------------|---------|----------------------|---------|----------|
| — | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_run1 | 0.0209 | [0.015, 0.029] | 0.4176 | [0.254, 0.576] | 7/8 |
| — | l3i_hipe-ocrepair-bench_v0.9_run2 | 0.0221 | [0.019, 0.026] | -0.0933 | [-0.203, 0.017] | 3/8 |

See [ranking-overall-test-weighted.tsv](results/system-rankings/ranking-overall-test-weighted.tsv) for full details.

## Per-language rankings

Per-language rankings are computed in the same way as the overall ranking, but restricted to the official test sets of the respective language.

¹ CIs for language scores are approximate (weighted average of per-test-set bootstrap CIs).

### Language: de (German) — test split

| Rank | System | Language cMER ↓ | 95% CI¹ | Language Pref Macro ↑ | 95% CI¹ | Test sets |
|------|--------|-----------------|---------|----------------------|---------|----------|
| 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_run1 | 0.0061 | [0.004, 0.008] | 0.8300 | [0.760, 0.889] | 4/4 |
| 2 | bnf-mistral_hipe-ocrepair-bench_v0.9_run3 | 0.0089 | [0.007, 0.011] | 0.7411 | [0.644, 0.822] | 4/4 |
| 3 | bnf-mistral_hipe-ocrepair-bench_v0.9_run2 | 0.0101 | [0.008, 0.013] | 0.9017 | [0.832, 0.956] | 4/4 |
| 4 | blocr_hipe-ocrepair-bench_v0.9_run1 | 0.0153 | [0.013, 0.018] | 0.5183 | [0.331, 0.684] | 4/4 |
| 5 | l3i_hipe-ocrepair-bench_v0.9_run1 | 0.0202 | [0.017, 0.023] | 0.4322 | [0.288, 0.577] | 4/4 |
| 7 | baseline-no-correction_hipe-ocrepair-bench_v0.9_run1 | 0.0286 | [0.026, 0.032] | 0.0000 | [0.000, 0.000] | 4/4 |

#### Systems with incomplete test set coverage

_Systems that have not processed all test sets are shown separately and not included in the official ranking._

| Rank | System | Language cMER ↓ | 95% CI¹ | Language Pref Macro ↑ | 95% CI¹ | Test sets |
|------|--------|-----------------|---------|----------------------|---------|----------|
| — | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_run1 | 0.0278 | [0.022, 0.035] | -0.0440 | [-0.258, 0.177] | 3/4 |
| — | l3i_hipe-ocrepair-bench_v0.9_run2 | 0.0286 | [0.024, 0.033] | 0.0200 | [-0.090, 0.130] | 1/4 |

See [ranking-language-de-test-weighted.tsv](results/system-rankings/ranking-language-de-test-weighted.tsv) for full details.

### Language: en (English) — test split

| Rank | System | Language cMER ↓ | 95% CI¹ | Language Pref Macro ↑ | 95% CI¹ | Test sets |
|------|--------|-----------------|---------|----------------------|---------|----------|
| 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_run1 | 0.0046 | [0.003, 0.006] | 0.9400 | [0.875, 0.990] | 2/2 |
| 2 | bnf-mistral_hipe-ocrepair-bench_v0.9_run3 | 0.0055 | [0.004, 0.007] | 0.9300 | [0.865, 0.980] | 2/2 |
| 3 | blocr_hipe-ocrepair-bench_v0.9_run1 | 0.0070 | [0.005, 0.010] | 0.8900 | [0.805, 0.965] | 2/2 |
| 4 | bnf-mistral_hipe-ocrepair-bench_v0.9_run2 | 0.0083 | [0.006, 0.011] | 0.8850 | [0.805, 0.950] | 2/2 |
| 5 | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_run1 | 0.0176 | [0.011, 0.026] | 0.6250 | [0.485, 0.755] | 2/2 |
| 6 | l3i_hipe-ocrepair-bench_v0.9_run1 | 0.0180 | [0.014, 0.023] | 0.3200 | [0.200, 0.435] | 2/2 |
| 8 | baseline-no-correction_hipe-ocrepair-bench_v0.9_run1 | 0.0215 | [0.018, 0.026] | 0.0000 | [0.000, 0.000] | 2/2 |

#### Systems with incomplete test set coverage

_Systems that have not processed all test sets are shown separately and not included in the official ranking._

| Rank | System | Language cMER ↓ | 95% CI¹ | Language Pref Macro ↑ | 95% CI¹ | Test sets |
|------|--------|-----------------|---------|----------------------|---------|----------|
| — | l3i_hipe-ocrepair-bench_v0.9_run2 | 0.0187 | [0.016, 0.022] | -0.1500 | [-0.260, -0.040] | 1/2 |

See [ranking-language-en-test-weighted.tsv](results/system-rankings/ranking-language-en-test-weighted.tsv) for full details.

### Language: fr (French) — test split

| Rank | System | Language cMER ↓ | 95% CI¹ | Language Pref Macro ↑ | 95% CI¹ | Test sets |
|------|--------|-----------------|---------|----------------------|---------|----------|
| 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_run1 | 0.0042 | [0.003, 0.006] | 0.9300 | [0.870, 0.975] | 2/2 |
| 2 | bnf-mistral_hipe-ocrepair-bench_v0.9_run3 | 0.0068 | [0.005, 0.009] | 0.9500 | [0.900, 0.990] | 2/2 |
| 3 | bnf-mistral_hipe-ocrepair-bench_v0.9_run2 | 0.0088 | [0.007, 0.011] | 0.8350 | [0.735, 0.920] | 2/2 |
| 4 | blocr_hipe-ocrepair-bench_v0.9_run1 | 0.0096 | [0.007, 0.012] | 0.7000 | [0.585, 0.800] | 2/2 |
| 5 | l3i_hipe-ocrepair-bench_v0.9_run1 | 0.0145 | [0.011, 0.019] | 0.3250 | [0.200, 0.445] | 2/2 |
| 6 | baseline-no-correction_hipe-ocrepair-bench_v0.9_run1 | 0.0176 | [0.014, 0.021] | 0.0000 | [0.000, 0.000] | 2/2 |
| 7 | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_run1 | 0.0185 | [0.011, 0.027] | 0.5950 | [0.450, 0.730] | 2/2 |

#### Systems with incomplete test set coverage

_Systems that have not processed all test sets are shown separately and not included in the official ranking._

| Rank | System | Language cMER ↓ | 95% CI¹ | Language Pref Macro ↑ | 95% CI¹ | Test sets |
|------|--------|-----------------|---------|----------------------|---------|----------|
| — | l3i_hipe-ocrepair-bench_v0.9_run2 | 0.0190 | [0.016, 0.023] | -0.1500 | [-0.260, -0.040] | 1/2 |

See [ranking-language-fr-test-weighted.tsv](results/system-rankings/ranking-language-fr-test-weighted.tsv) for full details.

## Results by dataset

### Dataset: dta19-l0_v0.1

#### Language: de (German) — test split

cMER micro [`cmer_micro`] — ordered ascending (lower is better)

| Rank | System | cMER micro ↓ | 95% CI | Pref cMER Macro ↑ | 95% CI | cMER macro | wMER macro |
|------|--------|--------------|--------|--------------|--------|------------|------------|
| 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_masked-test_de_run2 | 0.0029 | [0.002, 0.003] | 0.5000 | [0.233, 0.733] | 0.0029 | 0.0186 |
| 2 | baseline-no-correction_hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_masked-test_de_run1 | 0.0040 | [0.003, 0.005] | 0.0000 | [0.000, 0.000] | 0.0040 | 0.0259 |
| 3 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_masked-test_de_run1 | 0.0054 | [0.003, 0.009] | 0.1000 | [-0.200, 0.367] | 0.0050 | 0.0200 |
| 4 | l3i_hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_masked-test_de_run1 | 0.0058 | [0.004, 0.007] | -0.3333 | [-0.500, -0.167] | 0.0063 | 0.0382 |
| 5 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_masked-test_de_run3 | 0.0061 | [0.005, 0.008] | -0.3667 | [-0.667, -0.067] | 0.0062 | 0.0493 |
| 6 | blocr_hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_masked-test_de_run1 | 0.0076 | [0.006, 0.010] | -0.7000 | [-0.933, -0.433] | 0.0079 | 0.0328 |
| 7 | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_dta19-l0_v0.1_masked-test_de_run1 | 0.0114 | [0.009, 0.014] | -0.8333 | [-1.000, -0.633] | 0.0115 | 0.0505 |

See [ranking-dta19-l0_v0.1-test-de-cmer-micro.tsv](results/system-rankings/ranking-dta19-l0_v0.1-test-de-cmer-micro.tsv) for full details.

### Dataset: dta19-l1_v0.1

#### Language: de (German) — test split

cMER micro [`cmer_micro`] — ordered ascending (lower is better)

| Rank | System | cMER micro ↓ | 95% CI | Pref cMER Macro ↑ | 95% CI | cMER macro | wMER macro |
|------|--------|--------------|--------|--------------|--------|------------|------------|
| 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l1_v0.1_masked-test_de_run1 | 0.0054 | [0.004, 0.007] | 1.0000 | [1.000, 1.000] | 0.0061 | 0.0434 |
| 2 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l1_v0.1_masked-test_de_run2 | 0.0062 | [0.005, 0.007] | 1.0000 | [1.000, 1.000] | 0.0063 | 0.0332 |
| 3 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l1_v0.1_masked-test_de_run3 | 0.0077 | [0.006, 0.009] | 1.0000 | [1.000, 1.000] | 0.0087 | 0.0573 |
| 4 | blocr_hipe-ocrepair-bench_v0.9_dta19-l1_v0.1_masked-test_de_run1 | 0.0177 | [0.015, 0.020] | 0.6333 | [0.333, 0.867] | 0.0181 | 0.0952 |
| 5 | l3i_hipe-ocrepair-bench_v0.9_dta19-l1_v0.1_masked-test_de_run1 | 0.0223 | [0.020, 0.024] | 0.2000 | [0.000, 0.400] | 0.0226 | 0.1426 |
| 6 | baseline-no-correction_hipe-ocrepair-bench_v0.9_dta19-l1_v0.1_masked-test_de_run1 | 0.0240 | [0.023, 0.025] | 0.0000 | [0.000, 0.000] | 0.0241 | 0.1643 |
| 7 | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_dta19-l1_v0.1_masked-test_de_run1 | 0.0250 | [0.022, 0.029] | 0.1333 | [-0.200, 0.467] | 0.0268 | 0.0957 |

See [ranking-dta19-l1_v0.1-test-de-cmer-micro.tsv](results/system-rankings/ranking-dta19-l1_v0.1-test-de-cmer-micro.tsv) for full details.

### Dataset: dta19-l2_v0.1

#### Language: de (German) — test split

cMER micro [`cmer_micro`] — ordered ascending (lower is better)

| Rank | System | cMER micro ↓ | 95% CI | Pref cMER Macro ↑ | 95% CI | cMER macro | wMER macro |
|------|--------|--------------|--------|--------------|--------|------------|------------|
| 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l2_v0.1_masked-test_de_run1 | 0.0082 | [0.007, 0.010] | 1.0000 | [1.000, 1.000] | 0.0087 | 0.0589 |
| 2 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l2_v0.1_masked-test_de_run3 | 0.0121 | [0.009, 0.015] | 0.9333 | [0.800, 1.000] | 0.0127 | 0.0523 |
| 3 | bnf-mistral_hipe-ocrepair-bench_v0.9_dta19-l2_v0.1_masked-test_de_run2 | 0.0175 | [0.014, 0.022] | 1.0000 | [1.000, 1.000] | 0.0182 | 0.0628 |
| 4 | blocr_hipe-ocrepair-bench_v0.9_dta19-l2_v0.1_masked-test_de_run1 | 0.0338 | [0.031, 0.038] | 0.8667 | [0.667, 1.000] | 0.0356 | 0.1375 |
| 5 | l3i_hipe-ocrepair-bench_v0.9_dta19-l2_v0.1_masked-test_de_run1 | 0.0471 | [0.041, 0.053] | 0.2667 | [0.100, 0.467] | 0.0494 | 0.2335 |
| 6 | baseline-no-correction_hipe-ocrepair-bench_v0.9_dta19-l2_v0.1_masked-test_de_run1 | 0.0546 | [0.052, 0.057] | 0.0000 | [0.000, 0.000] | 0.0561 | 0.2875 |

See [ranking-dta19-l2_v0.1-test-de-cmer-micro.tsv](results/system-rankings/ranking-dta19-l2_v0.1-test-de-cmer-micro.tsv) for full details.

### Dataset: icdar2017_v1.1

#### Language: en (English) — test split

cMER micro [`cmer_micro`] — ordered ascending (lower is better)

| Rank | System | cMER micro ↓ | 95% CI | Pref cMER Macro ↑ | 95% CI | cMER macro | wMER macro |
|------|--------|--------------|--------|--------------|--------|------------|------------|
| 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_en_run1 | 0.0044 | [0.003, 0.006] | 0.9500 | [0.880, 1.000] | 0.0061 | 0.0191 |
| 2 | bnf-mistral_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_en_run3 | 0.0058 | [0.004, 0.007] | 0.9400 | [0.870, 0.990] | 0.0083 | 0.0265 |
| 3 | bnf-mistral_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_en_run2 | 0.0091 | [0.006, 0.012] | 0.9600 | [0.910, 1.000] | 0.0117 | 0.0377 |
| 4 | blocr_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_en_run1 | 0.0092 | [0.006, 0.014] | 0.9100 | [0.830, 0.980] | 0.0114 | 0.0303 |
| 5 | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_en_run1 | 0.0169 | [0.013, 0.022] | 0.7500 | [0.620, 0.860] | 0.0205 | 0.0539 |
| 6 | baseline-no-correction_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_en_run1 | 0.0260 | [0.021, 0.032] | 0.0000 | [0.000, 0.000] | 0.0300 | 0.1276 |
| 7 | l3i_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_en_run1 | 0.0261 | [0.020, 0.034] | 0.0700 | [-0.050, 0.180] | 0.0372 | 0.1282 |

See [ranking-icdar2017_v1.1-test-en-cmer-micro.tsv](results/system-rankings/ranking-icdar2017_v1.1-test-en-cmer-micro.tsv) for full details.

#### Language: fr (French) — test split

cMER micro [`cmer_micro`] — ordered ascending (lower is better)

| Rank | System | cMER micro ↓ | 95% CI | Pref cMER Macro ↑ | 95% CI | cMER macro | wMER macro |
|------|--------|--------------|--------|--------------|--------|------------|------------|
| 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_fr_run1 | 0.0040 | [0.003, 0.005] | 0.9800 | [0.940, 1.000] | 0.0039 | 0.0128 |
| 2 | blocr_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_fr_run1 | 0.0084 | [0.006, 0.011] | 0.9400 | [0.870, 0.990] | 0.0085 | 0.0253 |
| 3 | bnf-mistral_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_fr_run2 | 0.0084 | [0.007, 0.010] | 0.9200 | [0.840, 0.980] | 0.0085 | 0.0463 |
| 4 | bnf-mistral_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_fr_run3 | 0.0088 | [0.006, 0.012] | 0.9700 | [0.930, 1.000] | 0.0086 | 0.0467 |
| 5 | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_fr_run1 | 0.0137 | [0.009, 0.019] | 0.8300 | [0.720, 0.930] | 0.0136 | 0.0302 |
| 6 | baseline-no-correction_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_fr_run1 | 0.0184 | [0.015, 0.022] | 0.0000 | [0.000, 0.000] | 0.0186 | 0.1061 |
| 7 | l3i_hipe-ocrepair-bench_v0.9_icdar2017_v1.1_masked-test_fr_run1 | 0.0199 | [0.016, 0.025] | -0.0300 | [-0.140, 0.080] | 0.0263 | 0.1093 |

See [ranking-icdar2017_v1.1-test-fr-cmer-micro.tsv](results/system-rankings/ranking-icdar2017_v1.1-test-fr-cmer-micro.tsv) for full details.

### Dataset: impresso-snippets_v1.0

#### Language: de (German) — test split

cMER micro [`cmer_micro`] — ordered ascending (lower is better)

| Rank | System | cMER micro ↓ | 95% CI | Pref cMER Macro ↑ | 95% CI | cMER macro | wMER macro |
|------|--------|--------------|--------|--------------|--------|------------|------------|
| 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_de_run1 | 0.0058 | [0.004, 0.007] | 0.9600 | [0.920, 0.990] | 0.0067 | 0.0418 |
| 2 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_de_run3 | 0.0092 | [0.007, 0.011] | 0.9600 | [0.910, 1.000] | 0.0104 | 0.0503 |
| 3 | blocr_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_de_run1 | 0.0109 | [0.009, 0.013] | 0.7700 | [0.640, 0.890] | 0.0118 | 0.0438 |
| 4 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_de_run2 | 0.0113 | [0.009, 0.014] | 0.9700 | [0.920, 1.000] | 0.0127 | 0.0479 |
| 5 | l3i_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_de_run1 | 0.0153 | [0.012, 0.019] | 0.8200 | [0.710, 0.920] | 0.0178 | 0.0657 |
| 6 | l3i_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_de_run2 | 0.0286 | [0.024, 0.033] | 0.0200 | [-0.090, 0.130] | 0.0312 | 0.1669 |
| 7 | baseline-no-correction_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_de_run1 | 0.0296 | [0.025, 0.034] | 0.0000 | [0.000, 0.000] | 0.0319 | 0.1771 |
| 8 | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_de_run1 | 0.0342 | [0.026, 0.044] | 0.1600 | [-0.030, 0.350] | 0.0388 | 0.0995 |

See [ranking-impresso-snippets_v1.0-test-de-cmer-micro.tsv](results/system-rankings/ranking-impresso-snippets_v1.0-test-de-cmer-micro.tsv) for full details.

#### Language: en (English) — test split

cMER micro [`cmer_micro`] — ordered ascending (lower is better)

| Rank | System | cMER micro ↓ | 95% CI | Pref cMER Macro ↑ | 95% CI | cMER macro | wMER macro |
|------|--------|--------------|--------|--------------|--------|------------|------------|
| 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_en_run1 | 0.0049 | [0.003, 0.007] | 0.9300 | [0.870, 0.980] | 0.0048 | 0.0187 |
| 2 | blocr_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_en_run1 | 0.0049 | [0.004, 0.006] | 0.8700 | [0.780, 0.950] | 0.0052 | 0.0150 |
| 3 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_en_run3 | 0.0052 | [0.003, 0.007] | 0.9200 | [0.860, 0.970] | 0.0052 | 0.0134 |
| 4 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_en_run2 | 0.0074 | [0.005, 0.010] | 0.8100 | [0.700, 0.900] | 0.0077 | 0.0205 |
| 5 | l3i_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_en_run1 | 0.0099 | [0.008, 0.012] | 0.5700 | [0.450, 0.690] | 0.0102 | 0.0316 |
| 6 | baseline-no-correction_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_en_run1 | 0.0170 | [0.014, 0.020] | 0.0000 | [0.000, 0.000] | 0.0174 | 0.0723 |
| 7 | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_en_run1 | 0.0183 | [0.010, 0.031] | 0.5000 | [0.350, 0.650] | 0.0190 | 0.0389 |
| 8 | l3i_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_en_run2 | 0.0187 | [0.016, 0.022] | -0.1500 | [-0.260, -0.040] | 0.0194 | 0.0812 |

See [ranking-impresso-snippets_v1.0-test-en-cmer-micro.tsv](results/system-rankings/ranking-impresso-snippets_v1.0-test-en-cmer-micro.tsv) for full details.

#### Language: fr (French) — test split

cMER micro [`cmer_micro`] — ordered ascending (lower is better)

| Rank | System | cMER micro ↓ | 95% CI | Pref cMER Macro ↑ | 95% CI | cMER macro | wMER macro |
|------|--------|--------------|--------|--------------|--------|------------|------------|
| 1 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_fr_run1 | 0.0044 | [0.003, 0.006] | 0.8800 | [0.800, 0.950] | 0.0051 | 0.0249 |
| 2 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_fr_run3 | 0.0048 | [0.003, 0.007] | 0.9300 | [0.870, 0.980] | 0.0056 | 0.0216 |
| 3 | l3i_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_fr_run1 | 0.0091 | [0.006, 0.013] | 0.6800 | [0.540, 0.810] | 0.0106 | 0.0345 |
| 4 | bnf-mistral_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_fr_run2 | 0.0092 | [0.006, 0.012] | 0.7500 | [0.630, 0.860] | 0.0103 | 0.0462 |
| 5 | blocr_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_fr_run1 | 0.0108 | [0.008, 0.014] | 0.4600 | [0.300, 0.610] | 0.0121 | 0.0624 |
| 6 | baseline-no-correction_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_fr_run1 | 0.0169 | [0.013, 0.021] | 0.0000 | [0.000, 0.000] | 0.0182 | 0.1006 |
| 7 | l3i_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_fr_run2 | 0.0190 | [0.016, 0.023] | -0.1500 | [-0.260, -0.040] | 0.0206 | 0.1065 |
| 8 | Zakaria-ENSIAS_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_fr_run1 | 0.0233 | [0.014, 0.035] | 0.3600 | [0.180, 0.530] | 0.0258 | 0.0553 |

See [ranking-impresso-snippets_v1.0-test-fr-cmer-micro.tsv](results/system-rankings/ranking-impresso-snippets_v1.0-test-fr-cmer-micro.tsv) for full details.
