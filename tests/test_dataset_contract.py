"""数据集契约测试：对 datasets/tiny 与 datasets/hipe_2026 跑同一份契约。

对应 Docs/Design/10-datasets.md「验收」。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from datasetkit import ContractError, load_dataset, resolve

ROOT = Path(__file__).resolve().parents[1]
DATASETS = [ROOT / "datasets" / "tiny", ROOT / "datasets" / "hipe_2026"]

SPLIT_BY_NAME = {"tiny": "all", "hipe_2026": "dev"}


@pytest.fixture(params=DATASETS, ids=lambda p: p.name)
def dataset(request):
    return load_dataset(request.param)


def test_contract_entries(dataset):
    assert callable(dataset.loaders)
    assert callable(dataset.scorer)
    assert callable(dataset.default_instruction)
    info = dataset.info()
    assert info.notes.strip()  # 口径必须成文
    assert info.splits


def test_loaders_registry(dataset):
    loaders = dataset.loaders(split=SPLIT_BY_NAME[dataset.info().name])
    assert loaders, "loader 注册表为空"
    for key, loader in loaders.items():
        assert callable(loader), key
        tasks = list(loader())
        assert tasks, f"{key} 空流"
        assert all(t.task_id and isinstance(t.input, str) for t in tasks)


def test_loader_replayable(dataset):
    """同一 key 重复调用产出逐字段相同（可重放、可配对）。"""
    loaders = dataset.loaders(split=SPLIT_BY_NAME[dataset.info().name])
    key = next(iter(loaders))
    first = [(t.task_id, t.input, t.reference) for t in loaders[key]()]
    second = [(t.task_id, t.input, t.reference) for t in loaders[key]()]
    assert first == second


def test_task_ids_unique_across_loaders(dataset):
    """跨 key task_id 不撞（串联安全）。"""
    tasks = resolve(dataset, split=SPLIT_BY_NAME[dataset.info().name])
    ids = [t.task_id for t in tasks]
    assert len(ids) == len(set(ids))


def test_tasks_and_score_roundtrip(dataset):
    tasks = resolve(dataset, split=SPLIT_BY_NAME[dataset.info().name], limit=5)
    assert tasks, "数据集为空"
    task = next(t for t in tasks if t.reference is not None)
    record = dataset.scorer().score(task.input, task)  # identity：输出=输入
    assert record, "ScoreRecord 非空"
    assert all(isinstance(v, float) for v in record.values())


def test_masked_never_scored(dataset):
    tasks = resolve(dataset, split=SPLIT_BY_NAME[dataset.info().name], limit=50)
    masked = [t for t in tasks if t.reference is None]
    if not masked:  # hipe dev 无 masked 行，tiny 有 t3
        pytest.skip("该 split 无 masked 样本")
    from datasetkit import ScoreError

    with pytest.raises(ScoreError):
        dataset.scorer().score("x", masked[0])


def test_resolve_by_keys_and_limit(dataset):
    split = SPLIT_BY_NAME[dataset.info().name]
    loaders = dataset.loaders(split=split)
    key = next(iter(loaders))
    selected = resolve(dataset, split=split, keys=[key])
    assert [t.task_id for t in selected] == [t.task_id for t in loaders[key]()]
    limited = resolve(dataset, split=split, limit=3)
    assert len(limited) == 3


def test_resolve_rejects_unknown_key(dataset):
    with pytest.raises(ContractError):
        resolve(
            dataset, split=SPLIT_BY_NAME[dataset.info().name], keys=["__nope__"]
        )


def test_resolve_meta_filter(dataset):
    """meta 等值过滤：装配层截断器，不进数据集契约。"""
    split = SPLIT_BY_NAME[dataset.info().name]
    en = resolve(dataset, split=split, meta={"language": "en"})
    assert en and all(t.meta["language"] == "en" for t in en)
    none_ = resolve(dataset, split=split, meta={"language": "__nope__"})
    assert none_ == []


def test_contract_error_on_missing_entry(tmp_path):
    with pytest.raises(ContractError):
        load_dataset(tmp_path)
