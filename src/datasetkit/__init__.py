"""datasetkit：dataset.py 契约类型与装载器。

对应 Docs/Design/10-datasets.md「契约」节。

一个数据集 = 一个目录 + 一个 dataset.py，必须暴露四个入口：
loaders / scorer / default_instruction / info。物理布局完全隔离在契约背后。

loader 风格的选择接口（torch 式）：数据集给出一组具名 loader
（key 命名方案归数据集，写入 info().notes），组合权在调用方——
resolve() 按键选取 + itertools.chain 串联 + ids/limit 截断。
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

__all__ = [
    "Task",
    "DatasetInfo",
    "ScoreRecord",
    "ScoreError",
    "Scorer",
    "Loader",
    "ContractError",
    "load_dataset",
    "resolve",
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

Loader = Callable[[], Iterable[Task]]
"""零参 callable：一次调用 = 一条可重放的 Task 流。"""


class ScoreError(Exception):
    """评分失败（如对 masked task 调用 score）。"""


class Scorer(Protocol):
    def score(self, prediction: str, task: Task) -> ScoreRecord: ...


@dataclass(frozen=True)
class DatasetInfo:
    name: str
    version: str
    splits: tuple[str, ...]
    notes: str  # 口径与合理性限定 + loader key 命名方案；必须非空


class ContractError(Exception):
    """dataset.py 不满足契约。"""


_REQUIRED = ("loaders", "scorer", "default_instruction", "info")


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
    sys.modules[spec.name] = module  # dataclass 字符串注解等运行时解析依赖模块注册
    spec.loader.exec_module(module)
    missing = [name for name in _REQUIRED if not callable(getattr(module, name, None))]
    if missing:
        raise ContractError(f"{entry} 缺少契约入口: {missing}")
    info = module.info()
    if not isinstance(info.notes, str) or not info.notes.strip():
        raise ContractError(f"{entry}: info().notes 必须非空（口径必须成文）")
    module.__dataset_dir__ = str(entry.parent.resolve())  # 供报告落盘
    return module


def resolve(
    dataset: Any,
    *,
    split: str,
    keys: list[str] | None = None,
    meta: dict[str, str] | None = None,
    ids: list[str] | None = None,
    limit: int | None = None,
) -> list[Task]:
    """处理对象的选择：按 key 选 loader（缺省全部）+ 串联，再依次经
    meta（task.meta 等值过滤，AND）/ ids / limit 截断。

    组合在装配层完成，不触碰数据集的物理布局。
    """
    available = dataset.loaders(split=split)
    if keys is None:
        selected = list(available)
    else:
        unknown = [k for k in keys if k not in available]
        if unknown:
            raise ContractError(
                f"未知 loader key {unknown}（{dataset.info().name} 可用：{sorted(available)}）"
            )
        selected = list(keys)
    tasks = list(
        itertools.chain.from_iterable(available[k]() for k in selected)
    )
    if meta:
        tasks = [
            t
            for t in tasks
            if all(str(t.meta.get(k)) == v for k, v in meta.items())
        ]
    if ids is not None:
        wanted = set(ids)
        tasks = [t for t in tasks if t.task_id in wanted]
    if limit is not None:
        tasks = tasks[:limit]
    return tasks
