"""Statistical guardrails: source clusters must remain intact across noise levels."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "paper_bootstrap", Path(__file__).resolve().parents[1] / "scripts" / "cluster_bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def sample_rows():
    # Perfect correlation within each source, opposite effects between sources.
    return [{"model": "test", "arm": arm, "task_id": f"l{level}/{source}",
             "source_document": source, "cmer": effect if arm == "b" else 0.0}
            for source, effect in [("one", -10.0), ("two", 10.0)]
            for level in range(3) for arm in ("a", "b")]


def test_cluster_resampling_preserves_perfect_within_source_dependence():
    # Drawing two whole clusters has effects {-10, 0, 10} with probabilities
    # {1/4, 1/2, 1/4}. Row resampling or sampling a row from every source fails.
    for metric in ("cmer", "p90"):
        result = bootstrap.paired_cluster(sample_rows(), "test", "a", "b", metric, 2000, 0)
        assert result["ci95"] == [-10.0, 10.0]
        assert result["n_source_documents"] == 2
        assert result["n_tasks"] == 6
    assert bootstrap.paired_cluster(sample_rows(), "test", "a", "b", "cmer", 2000, 0)["difference"] == 0


def test_rejects_unpaired_and_duplicate_rows():
    with pytest.raises(ValueError, match="same nonempty"):
        bootstrap.paired_cluster(sample_rows()[:-1], "test", "a", "b", "cmer", 20, 0)
    rows = sample_rows()
    with pytest.raises(ValueError, match="Duplicate"):
        bootstrap.paired_cluster(rows + rows[:1], "test", "a", "b", "cmer", 20, 0)
