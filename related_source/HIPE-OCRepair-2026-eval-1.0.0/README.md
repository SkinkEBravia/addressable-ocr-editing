# HIPE-OCRepair 2026 – Evaluation

This repository contains the official evaluation toolkit for the HIPE-OCRepair 2026 competition, including:

- the test data used for the evaluation
- the system submissions
- the [HIPE-OCRepair-scorer](https://github.com/hipe-eval/HIPE-OCRepair-scorer) (as a Python package) and the evaluation scripts used to score system outputs
- the evaluation results
- a Makefile to run the whole evaluation process

The repository is designed to ensure transparent and reproducible evaluation of all submitted systems.

**For more information, also have a look at:**

- :books: [ HIPE evaluation campaigns](https://hipe-eval.github.io)
- :link: [HIPE-OCRepair 2026 Website](https://hipe-eval.github.io/HIPE-OCRepair-2026/)
- :checkered_flag: HIPE-OCRepair-2026 results on the [website](https://hipe-eval.github.io/HIPE-OCRepair-2026/results)
- :open_file_folder: HIPE-OCRepair-2026 [data set releases](https://github.com/hipe-eval/HIPE-OCRepair-2026-data/releases)
- :low_brightness: HIPE-OCRepair-2026 [baseline](https://github.com/hipe-eval/HIPE-OCRepair-2026-baseline)

## Table of Contents

- [Task](#task)
- [Repository setup](#repository-set-up)
  - [Repository structure](#repository-structure)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
    - [To run the evaluation](#to-run-the-evaluation)
- [Submission format](#submission-format)
- [Official competition data](#official-competition-data)
- [Evaluation outputs](#evaluation-outputs)
  - [Per-run scores](#per-run-scores)
  - [Rankings](#rankings)
  - [Qualitative error analysis](#qualitative-error-analysis)
  - [Pairwise significance testing](#pairwise-significance-testing)
- [Metrics and rankings](#metrics-and-rankings)
  - [Aggregation levels](#aggregation-levels)
  - [Metric definitions used in the reports](#metric-definitions-used-in-the-reports)
  - [Confidence intervals](#confidence-intervals)
  - [Per-dataset scores and overall averages](#per-dataset-scores-and-overall-averages)
  - [Primary and secondary ranking criteria](#primary-and-secondary-ranking-criteria)
  - [Official competition ranking across test sets](#official-competition-ranking-across-test-sets)
  - [Per-language rankings](#per-language-rankings)
- [Results](#results)

## Task

The shared task focuses on OCR post-correction for historical documents. Participants develop systems that automatically correct OCR errors in historical text transcription units that are larger than a single line. Depending on the dataset, a transcription unit may correspond to a paragraph, article, page, or semantic chunk, allowing systems to make more global corrections than line-level post-correction.

Inputs include the OCR text to correct together with document metadata used for matching and contextualisation.

System outputs are evaluated against gold-standard reference data using the official evaluation scorer, which applies a light normalization to the reference and hypothesis texts before scoring.

## Repository set up

### Repository structure

```bash
data/
  reference/              # Gold-standard reference JSONL files (one per dataset/split/language)
  systems/                # Participant submission JSONL files
lib/
  score_one.py                # Score a single hypothesis against its reference
  build_rankings.py           # Aggregate per-run scores into ranked TSV files
  build_results_md.py         # Render TSV rankings as a Markdown results page
  create_dummy_baselines.py   # Generate dummy baseline hypotheses from reference files
  pairwise_significance.py    # Compare two specific systems using paired bootstrap
  pairwise_overlaps.py        # Test all consecutive systems with overlapping CIs
  competition_config.json     # Official competition test sets and design weights
  teams.json                  # Team name → institution mapping
results/                      # Pipeline output (regenerated; not committed)
  per-run/                    # Detailed JSON scores and logs for each submission
  system-rankings/            # TSV ranking tables
  text-views/                 # Plain text exports for diff-based error inspection
  text-views-normalized/      # Normalized text views (as used in scoring)
  pairwise-overlaps.tsv       # Pairwise significance test results
HIPE_OCRepair_2026_evaluation_results.md        # Final results page (generated)
```

### Prerequisites

Before installing, ensure you have the following:

- **Python 3.10 or newer** — check with `python3 --version`
- **GNU Make 3.81+** (2006 or later) — standard on Linux and macOS
- **Git** — for cloning the repository
- **GNU grep** (required for pairwise significance testing analytics)
  - **Linux**: already installed by default
  - **macOS**: install with `brew install grep` (BSD grep doesn't support the `-P` flag used in analytics commands)

**Platform notes:**

- **Linux**: all tools typically pre-installed
- **macOS**: requires Homebrew installation of GNU grep for full analytics support
- **Windows**: use WSL (Windows Subsystem for Linux) for best compatibility

### Installation

Clone the repository and install the required dependencies:

```bash
git clone git@github.com:impresso/HIPE-OCRepair-2026-eval.git
cd HIPE-OCRepair-2026-eval

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

The `requirements.txt` installs the
[HIPE-OCRepair-scorer](https://github.com/hipe-eval/HIPE-OCRepair-scorer) from GitHub.
This will also install all transitive dependencies (numpy, jiwer, etc.).

To update the scorer to the latest version:

```bash
pip install --upgrade -r requirements.txt
```

**Verify installation:**

```bash
make help                    # Show all available targets
python3 --version            # Should be 3.10 or newer
make --version               # Should be GNU Make 3.81+
grep --version | head -1     # On macOS, ensure you're using GNU grep
```

#### To run the evaluation

```bash
make validate-submissions # Validate files in data/systems/ against the official JSON schema
make eval-full          # Score submissions, build rankings and results MD
make eval-full-refresh  # Remove all derived files and re-run from scratch
```

Run `make` to see all available targets.

## Submission format

Submission files are JSONL files (one JSON object per line). Teams submit them by email. After an organizer-side format check, validated submissions are added to this repository under `data/systems/`, and team metadata is updated in `lib/teams.json`.

Each team submission record must contain the following fields:

Unlike reference files, submission files do not contain a `ground_truth` field.

```json
{
  "document_metadata": {
    "document_id": "unique-id",
    "primary_dataset_name": "unversioned dataset name as it appears in the reference file (e.g., icdar2017, impresso-snippets, dta19-l0)",
    "language": "Language code (e.g., en, de, fr)"
  },
  "ocr_hypothesis": {
    "transcription_unit": "Original OCR text (as provided)"
  },
  "ocr_postcorrection_output": {
    "transcription_unit": "Your system's corrected text"
  }
}
```

For team submissions, the only field that is evaluated as system output is `ocr_postcorrection_output.transcription_unit`. The `document_metadata` fields are used to identify and match records, and the OCR hypothesis is kept as provided in the released test files.

Submission files should validate against the official JSON schema:

- Schema: https://github.com/hipe-eval/HIPE-OCRepair-2026-data/blob/main/schema/hipe-ocrepair.schema.json
- Local check in this repository: `make validate-submissions`

**File naming convention:**
A submission filename is formed by prepending your team name and appending a run suffix to the corresponding released masked test filename:

```
<teamname>_<reference-stem>_run<N>.jsonl
```

where `<reference-stem>` is the reference file's name without the `.jsonl` extension, and `run<N>` ∈ `{run1, run2, run3}`.

For this repository, the split component follows this policy:

- files in `data/reference/` use `<split> = test` because they contain the ground truth
- files in `data/systems/` use `<split> = masked-test` because they are based on the masked test release sent to participants

Expanded, this gives:

```
<teamname>_hipe-ocrepair-bench_<bench-version>_<dataset>_<dataset-version>_<split>_<language>_run<N>.jsonl
```

- `<teamname>`: lowercase alphanumeric characters and hyphens only — **no underscores**
- `<bench-version>`: benchmark version, currently `v0.9`
- `<dataset>_<dataset-version>`: exact versioned dataset identifier — see table below
- `<split>`: `masked-test` for participant submission files in `data/systems/`; the matching files in `data/reference/` use `test`
- `<language>`: `en`, `de`, or `fr`
- `run<N>`: `run1`, `run2`, or `run3` — up to 3 runs per reference file per team

Example submission file: `myteam_hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_masked-test_de_run1.jsonl`

Matching reference file in `data/reference/`: `hipe-ocrepair-bench_v0.9_impresso-snippets_v1.0_test_de.jsonl`

All submission files will be placed in `data/systems/`.

### Official competition data

Only the following datasets are part of the official ICDAR 2026 competition evaluation in this repository:

- `icdar2017` (`en`, `fr`)
- `impresso-snippets` (`de`, `en`, `fr`)
- `dta19-l0`, `dta19-l1`, `dta19-l2` (`de`)

`impresso-nzz` and `overproof-combined` are part of HIPE-OCRepair-bench, but 
are not part of the competition evaluation.

The exact versioned dataset identifiers are:

| Source dataset    | Versioned dataset identifier | Language(s) |
| ----------------- | ---------------------------- | ----------- |
| icdar2017         | `icdar2017_v1.1`             | en, fr      |
| impresso-snippets | `impresso-snippets_v1.0`     | de, en, fr  |
| impresso-nzz      | `impresso-nzz_v1.1`          | de          |
| dta19 (level 0)   | `dta19-l0_v0.1`              | de          |
| dta19 (level 1)   | `dta19-l1_v0.1`              | de          |
| dta19 (level 2)   | `dta19-l2_v0.1`              | de          |
| overproof         | `overproof-combined_v1.0`    | en          |

#### Note on DTA test sets:
After test set creation, it was discovered that some DTA snippets lack coherent paragraph structure, with content from different lines mixed together. This makes meaningful OCR post-correction challenging, particularly for LLM-based approaches. To ensure fair evaluation, the DTA test sets (all three noise levels: `dta19-l0`, `dta19-l1`, `dta19-l2`) were reduced from 80 to 30 transcription units each, retaining only documents from the three most coherent books:

- `1802-novalis_ofterdingen` (10 transcription units)
- `1815-hoffmann_elixiere01` (10 transcription units)
- `1826-eichendorff_taugenichts` (10 transcription units)

The following five books were excluded from all DTA test sets: `1817-hoffmann_nachtstuecke01`, `1832-lenau_gedichte`, `1834-wienbarg_feldzuege`, `1852-alexis_ruhe01`, and `1863-schleiden_menschengeschlecht`.


For more information on data, please refer to the [data section](https://github.
com/hipe-eval/HIPE-OCRepair-2026-data/blob/main/README-Participation-Guidelines.md#5-evaluation-campaign-and-system-responses) of the participation guidelines of the [HIPE-OCRepair-2026 data repository](https://github.com/hipe-eval/HIPE-OCRepair-2026-data/tree/main/).

## Evaluation outputs

The `results/` directory contains detailed scoring information and qualitative analysis aids:

### Per-run scores

`results/per-run/` contains detailed JSON files for each submission with:

- Aggregated scores (`cmer_micro`, `cmer_macro`, `wmer_micro`, `wmer_macro`, preference scores)
- 95% bootstrap confidence intervals
- Per-dataset fold scores
- `.log` files with scorer output

### Rankings

`results/system-rankings/` contains TSV files with system rankings:

- Per-dataset rankings: `ranking-<dataset>-<split>-<lang>-cmer-micro.tsv`
- Per-language weighted rankings: `ranking-language-<lang>-test-weighted.tsv`
- Overall competition ranking: `ranking-overall-test-weighted.tsv`

Rankings show systems ordered by primary metric (`cmer_micro`), with secondary criterion (`pref_score_cmer_macro`) and confidence intervals.

### Qualitative error analysis

For qualitative error inspection, the evaluation pipeline exports plain text views that can be compared using standard diff tools:

- **`results/text-views/`**: Original text views with three files per submission:
  - `.orig.txt` — original OCR input
  - `.cor.txt` — system-corrected output
  - `.gth.txt` — ground truth reference

- **`results/text-views-normalized/`**: Same structure but with normalized texts (lowercased, punctuation removed, whitespace collapsed) — exactly as used during scoring

To inspect errors for a specific run, compare files with any diff tool:

```bash
# Compare system output to ground truth (normalized view)
diff results/text-views-normalized/<runname>.cor.txt results/text-views-normalized/<runname>.gth.txt

# Or use a visual diff tool
code --diff results/text-views-normalized/<runname>.cor.txt results/text-views-normalized/<runname>.gth.txt
```

### Pairwise significance testing

While ranking tables show 95% confidence intervals for each system, overlapping CIs cannot definitively determine whether two systems are significantly different. To address this, pairwise significance testing using paired bootstrap methods is available.

**`results/pairwise-overlaps.tsv`** contains statistical comparisons of all consecutive systems with overlapping confidence intervals, showing:

- Mean difference between systems
- 95% CI of the difference
- p-values and significance indicators
- Winner determination or statistical ties

Generate the pairwise analysis with:

```bash
make pairwise-overlaps
```

For detailed documentation on interpretation and use cases:

- [PAIRWISE_TESTING.md](PAIRWISE_TESTING.md) — Full statistical methodology and analysis guide
- [QUICKSTART_PAIRWISE.md](QUICKSTART_PAIRWISE.md) — Quick start guide with practical examples

## Metrics and rankings

The primary evaluation metric is **character-level Match Error Rate (cMER)**. Secondary metrics include word-level MER and preference-based comparison scores against the raw OCR baseline.

Before scoring, texts are normalized using a light IR-style normalization that roughly mimics what an indexing and retrieval system would apply:

- lowercased
- punctuation and other non-word characters replaced by spaces
- underscores replaced by spaces
- repeated whitespace collapsed

Evaluation is therefore **case-insensitive** and **punctuation-insensitive**, but still sensitive to accented characters (for example, `é` and `e` remain different).

A cMER of 0.05 means that the hypothesis and reference differ by 5% at the character level.

### Aggregation levels

Each test dataset consists of a set of **transcription units**. All metrics are first computed at the level of individual transcription units and then aggregated.

For each dataset, the scorer reports:

- **`cmer_micro`**: character-level MER obtained by summing alignment counts across all transcription units in the dataset and computing cMER once from the summed totals within a test set
- **`cmer_macro`**: arithmetic mean of the transcription-unit-level cMER scores within a test set
- **`wmer_micro`** and **`wmer_macro`** are computed in the same way as cmer_micro and cmer_macro, but using word-level alignments produced by jiwer.process_words(...) after normalization. Here, hits, substitutions, deletions, and insertions are counted over aligned word sequences rather than character sequences.

In other words:

- **micro** aggregation gives more weight to longer transcription units in a test set
- **macro** aggregation gives equal weight to each transcription unit in a test set

### Metric definitions used in the reports

The evaluation reports show the following metrics:

- **`cmer_micro`**: micro-averaged character-level Match Error Rate
- **`cmer_macro`**: macro-averaged character-level Match Error Rate
- **`wmer_micro`**: micro-averaged word-level Match Error Rate
- **`wmer_macro`**: macro-averaged word-level Match Error Rate
- **`pref_score_cmer_macro`**: macro-averaged preference score based on cMER

At the transcription-unit level, MER is defined as:

$$
\mathrm{MER} = \frac{S + D + I}{H + S + D + I}
$$

where \(H\) = hits, \(S\) = substitutions, \(D\) = deletions, and \(I\) = insertions at the relevant alignment level (characters for cMER, words for wMER).

For a dataset with transcription units \(i = 1, ..., N\):

```math
\mathrm{cMER\_micro} =
\frac{\sum_i S_i + \sum_i D_i + \sum_i I_i}
     {\sum_i H_i + \sum_i S_i + \sum_i D_i + \sum_i I_i}
```

```math
\mathrm{wMER\_micro} =
\frac{\sum_i S_i + \sum_i D_i + \sum_i I_i}
     {\sum_i H_i + \sum_i S_i + \sum_i D_i + \sum_i I_i}
```

```math
\mathrm{cMER\_macro} = \frac{1}{N} \sum_{i=1}^{N} \mathrm{cMER}_{i}
```

```math
\mathrm{wMER\_macro} = \frac{1}{N} \sum_{i=1}^{N} \mathrm{wMER}_{i}
```

The preference score for one transcription unit _i_ is defined as follows:

```math
\mathrm{pref}(i) =
\begin{cases}
1 & \text{if the system score is better than the raw OCR score} \\
0 & \text{if both scores are equal} \\
-1 & \text{if the system score is worse than the raw OCR score}
\end{cases}
```

The reported preference metrics are macro averages over transcription units:

```math
\mathrm{pref\_score\_cMER\_macro} =
\frac{1}{N} \sum_{i=1}^{N} \mathrm{pref\_cMER}(i)
```

### Confidence intervals

The report tables include **95% bootstrap confidence intervals** for **`cmer_micro`** and **`pref_score_cmer_macro`**. These intervals are based on **10,000 bootstrap resamples** of the transcription units.

For **micro-averaged** metrics such as `cmer_micro`, the scorer resamples transcription units, sums their alignment counts, and recomputes the score from the pooled totals. For **macro-averaged** metrics such as `pref_score_cmer_macro`, it resamples the transcription units, recomputes the per-unit scores, and then takes their mean.

The reported lower and upper bounds correspond to the **2.5th** and **97.5th
percentiles** of the bootstrap distribution. In `fold_scores`, each metric is stored as
`(score, low_ci, high_ci)`. In `averaged_scores`, the central value is the unweighted
mean across datasets, and the confidence interval is obtained from the mean of the
per-dataset bootstrap samples.

### Per-dataset scores and overall averages

Scoring is performed **per dataset** (using `primary_dataset_name` as the grouping key). In the output of the scorer, these dataset-level results are stored under `fold_scores`.

The overall results in `averaged_scores` are then computed as the **unweighted mean across datasets** of the corresponding dataset-level scores.

This means that:

- `fold_scores[dataset]["cmer_micro"]` is the **micro cMER within that dataset**
- `averaged_scores["cmer_micro"]` is the **mean of the dataset-level micro cMER values**

So the overall average is **not** a single global micro-average over all transcription units from all datasets combined. Instead, it is an equal-weight average over datasets.

### Primary and secondary ranking criteria

The **primary per-test-set ranking metric** is **`cmer_micro`**:

- lower is better
- computed separately for each dataset
- longer transcription units contribute more within a dataset

The **secondary ranking metric** is **`pref_score_cmer_macro`**:

- higher is better
- measures how consistently a system improves over the raw OCR input across transcription units
- each transcription unit contributes equally

### Official competition ranking across test sets

The scorer outputs per-dataset scores, including `cmer_micro` for each dataset.
The **official competition ranking** is computed separately from these scorer outputs as a **weighted mean of per-test-set `cmer_micro`** across the 8 official test sets.

The weighting scheme is defined by the competition design and is **not** the same as the scorer’s internal `averaged_scores`, which uses an unweighted mean across datasets.

The weights are chosen so that the language-level contributions remain balanced:

- for **English** and **French**, each language score is based on **two test sets**, each with weight **1**
- for **German**, the score is based on **four test sets**: `impresso-snippets` with weight **1**, and the three DTA test sets (`dta19-l0`, `dta19-l1`, `dta19-l2`) with weight **1/3** each

Thus, the three DTA test sets together contribute the same total weight as one other test set. For German, this makes the combined DTA contribution match the weight of `impresso-snippets`, just as English and French each combine two equally weighted test sets.

| Unversioned dataset identifier | Lang | Weight |
| ------------------------------ | ---- | ------ |
| `dta19-l0`                     | de   | 1/3    |
| `dta19-l1`                     | de   | 1/3    |
| `dta19-l2`                     | de   | 1/3    |
| `impresso-snippets`            | de   | 1      |

| Unversioned dataset identifier | Lang | Weight |
| ------------------------------ | ---- | ------ |
| `icdar2017`                    | en   | 1      |
| `impresso-snippets`            | en   | 1      |

| Unversioned dataset identifier | Lang | Weight |
| ------------------------------ | ---- | ------ |
| `icdar2017`                    | fr   | 1      |
| `impresso-snippets`            | fr   | 1      |

`impresso-nzz` and `overproof-combined` are not part of the official shared-task evaluation in this repository and therefore do not contribute to the official rankings.

### Per-language rankings

In addition to the overall competition ranking, we report **per-language rankings** of submitted runs.

For a given language, the ranking is computed as a **weighted mean of per-test-set `cmer_micro`** over the official test sets for that language. The secondary criterion is the corresponding **weighted mean of `pref_score_cmer_macro`**.

This means in terms of unversioned datasets:

- for **English**, the language score is the mean over `icdar2017` and `impresso-snippets`
- for **French**, the language score is the mean over `icdar2017` and `impresso-snippets`
- for **German**, the language score is computed from `impresso-snippets` with weight `1` and from `dta19-l0`, `dta19-l1`, and `dta19-l2` with weight `1/3` each

As in the overall ranking, these language-level rankings are based on weighted combinations of **per-test-set scores**. They should not be confused with the scorer’s internal notions of **micro** and **macro**, which refer to aggregation over transcription units within a dataset.

## Results

The evaluation results are available in [HIPE_OCRepair_2026_evaluation_results.md](HIPE_OCRepair_2026_evaluation_results.md) and on the [HIPE-OCRepair-2026 website](https://hipe-eval.github.io/HIPE-OCRepair-2026/results).

The **official competition ranking** is computed as described above: a **weighted mean of `cmer_micro`** across the official test sets, with the corresponding **weighted mean of `pref_score_cmer_macro`** as secondary criterion.
