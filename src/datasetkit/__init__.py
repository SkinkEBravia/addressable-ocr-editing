"""datasetkit：dataset.py 契约类型与装载器。

对应 Docs/Design/10-datasets.md「契约」节。

一个数据集 = 一个目录 + 一个 dataset.py，必须暴露四个入口：
tasks / scorer / default_instruction / info。物理布局完全隔离在契约背后。
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol

__all__ = [
    "Task",
    "DatasetInfo",
    "ScoreRecord",
    "ScoreError",
    "Scorer",
    "ContractError",
    "load_dataset",
]


@dataclass(frozen=True)
class Task:
    """LLM 要修改的对象 + 评判依据。"""

    task_id: str  # 数据集内唯一，落盘与报告的主键
    input: str  # 待处理文本
    reference: str | None  # gold；None = masked，不参与出数
    meta: dict[str, Any] = field(default_factory=dict)  # 报告切片维度


ScoreRecord = dict[str, float]
"""指标名 -> 值。指标语义归数据集，报告层只按名聚合。"""


class ScoreError(Exception):
    """评分失败（如对 masked task 调用 score）。"""


class Scorer(Protocol):
    def score(self, prediction: str, task: Task) -> ScoreRecord: ...


@dataclass(frozen=True)
class DatasetInfo:
    name: str
    version: str
    splits: tuple[str, ...]
    granularities: tuple[str, ...]
    notes: str  # 口径与合理性限定；必须非空


class ContractError(Exception):
    """dataset.py 不满足契约。"""


_REQUIRED = ("tasks", "scorer", "default_instruction", "info")


def load_dataset(path: Path | str) -> Any:
    """装载含 dataset.py 的目录，校验契约后返回模块对象。"""
    path = Path(path)
    entry = path / "dataset.py" if path.is_dir() else path
    if not entry.is_file():
        raise ContractError(f"数据集入口不存在: {entry}")
    spec = importlib.util.spec_from_file_location(
        f"dataset_{abs(hash(str(entry.resolve())))}", entry
    )
    if spec is None or spec.loader is None:
        raise ContractError(f"无法装载数据集: {entry}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    missing = [name for name in _REQUIRED if not callable(getattr(module, name, None))]
    if missing:
        raise ContractError(f"{entry} 缺少契约入口: {missing}")
    info = module.info()
    if not isinstance(info.notes, str) or not info.notes.strip():
        raise ContractError(f"{entry}: info().notes 必须非空（口径必须成文）")
    module.__dataset_dir__ = str(entry.parent.resolve())  # 供报告落盘
    return module


def select(
    dataset: Any,
    *,
    split: str,
    granularity: str | None = None,
    ids: list[str] | None = None,
    languages: list[str] | None = None,
    limit: int | None = None,
) -> Iterable[Task]:
    """处理对象的选择：全部经 tasks() 参数透传，调用方不触碰文件。"""
    return dataset.tasks(
        split=split, granularity=granularity, ids=ids, languages=languages, limit=limit
    )
