"""数据集契约测试：对 datasets/tiny 与 datasets/hipe_2026 跑同一份契约。

对应 Docs/Design/10-datasets.md「验收」。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from datasetkit import ContractError, load_dataset

ROOT = Path(__file__).resolve().parents[1]
DATASETS = [ROOT / "datasets" / "tiny", ROOT / "datasets" / "hipe_2026"]

SPLIT_BY_NAME = {"tiny": "all", "hipe_2026": "dev"}


@pytest.fixture(params=DATASETS, ids=lambda p: p.name)
def dataset(request):
    return load_dataset(request.param)


def test_contract_entries(dataset):
    assert callable(dataset.tasks)
    assert callable(dataset.scorer)
    assert callable(dataset.default_instruction)
    info = dataset.info()
    assert info.notes.strip()  # 口径必须成文
    assert info.splits and info.granularities


def test_tasks_and_score_roundtrip(dataset):
    tasks = dataset.tasks(split=SPLIT_BY_NAME[dataset.info().name], limit=5)
    assert tasks, "数据集为空"
    task = next(t for t in tasks if t.reference is not None)
    record = dataset.scorer().score(task.input, task)  # identity：输出=输入
    assert record, "ScoreRecord 非空"
    assert all(isinstance(v, float) for v in record.values())


def test_masked_never_scored(dataset):
    tasks = dataset.tasks(split=SPLIT_BY_NAME[dataset.info().name], limit=50)
    masked = [t for t in tasks if t.reference is None]
    if not masked:  # hipe dev 无 masked 行，tiny 有 t3
        pytest.skip("该 split 无 masked 样本")
    from datasetkit import ScoreError

    with pytest.raises(ScoreError):
        dataset.scorer().score("x", masked[0])


def test_selection_by_ids_and_limit(dataset):
    tasks = dataset.tasks(split=SPLIT_BY_NAME[dataset.info().name], limit=3)
    ids = [t.task_id for t in tasks[:2]]
    selected = dataset.tasks(split=SPLIT_BY_NAME[dataset.info().name], ids=ids)
    assert [t.task_id for t in selected] == ids


def test_contract_error_on_missing_entry(tmp_path):
    with pytest.raises(ContractError):
        load_dataset(tmp_path)
