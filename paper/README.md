# Manuscript and reproducible analysis

This manuscript is prepared for arXiv submission.

From the repository root, Python 3.12+:

```sh
python -m pip install -r paper/requirements.txt
python scripts/cluster_bootstrap.py --json paper/data/cluster_bootstrap.json
python scripts/paper_tables.py
python paper/figures/make_figures.py
```

The bootstrap and table generators use only the Python standard library.
Figures require the pinned dependencies; their versions match the local build.
All three analysis commands use the included snapshot and make no model API calls.

To compile, change into `paper/` and run:

```sh
pdflatex -halt-on-error -interaction=nonstopmode paper.tex
bibtex paper
pdflatex -halt-on-error -interaction=nonstopmode paper.tex
pdflatex -halt-on-error -interaction=nonstopmode paper.tex
```

On this machine the executables are under
`E:\Programs\Portablemiktex-portable\texmfs\install\miktex\bin\x64`.
The generated `.bbl` is included for source submission portability.

## Provenance and limits

`data/results.csv` has 792 model-output rows (3 configurations × 8 arms × 33
tasks), plus 99 no-edit rows. `data/provenance.json` records SHA-256 hashes of
the 24 local source reports and their saved public configurations. The hashes
are provenance pointers, not independent verification when those reports are
unavailable. No raw transcripts, predictions, credentials, or reasoning traces
are included in this derived snapshot.

To rebuild the snapshot from the original local reports:

```sh
python scripts/export_paper_results.py --runs runs --output paper/data
```

The exporter checks paired task sets and identical no-edit scores across arms.
`tests/test_paper_bootstrap.py` checks clustered resampling against a synthetic
perfectly correlated example and rejects incomplete/duplicate pairings.

The source reports and tape/message/IR artifacts are not included here. Their
separate archival release remains necessary for independent scoring and replay.
The paper explicitly distinguishes this limitation from regenerating statistics
from a frozen score snapshot. New inference replications are **not** part of this revision.

See `EXPERIMENT_GAPS.md` for the prioritized experimental follow-up plan.
