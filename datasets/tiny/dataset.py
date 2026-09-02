"""tiny：契约夹具数据集（Docs/Design/10-datasets.md「测试入口」）。

布局：ocr/<id>.txt + gold/<id>.txt（缺 gold 文件 = masked，reference=None）。
评分：简易字符错误率（cER），只用于测试自洽，口径不与任何官方成绩可比。
loader key：tiny/en/unit（单一子集，命名与真实数据集同构）。
"""

from __future__ import annotations

from pathlib import Path

from datasetkit import DatasetInfo, Loader, ScoreError, Task

_DIR = Path(__file__).resolve().parent

__all__ = ["loaders", "scorer", "default_instruction", "info"]

_SPLITS = ("all",)


def _load() -> list[Task]:
    out: list[Task] = []
    for path in sorted((_DIR / "ocr").glob("*.txt")):
        task_id = path.stem
        gold_path = _DIR / "gold" / f"{task_id}.txt"
        reference = (
            gold_path.read_text(encoding="utf-8") if gold_path.is_file() else None
        )
        out.append(
            Task(
                task_id=task_id,
                input=path.read_text(encoding="utf-8"),
                reference=reference,
                meta={"language": "en"},
            )
        )
    return out


def loaders(*, split: str = "all") -> dict[str, Loader]:
    if split != "all":
        raise ValueError(f"tiny 只有 split='all'，got {split!r}")
    return {"tiny/en/unit": _load}


def _edit_distance(a: str, b: str) -> int:
    """标准 Levenshtein（夹具数据很短，无性能要求）。"""
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            curr.append(min(curr[-1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        prev = curr
    return prev[-1]


class _Scorer:
    def score(self, prediction: str, task: Task) -> dict[str, float]:
        if task.reference is None:
            raise ScoreError(f"masked task 不出数: {task.task_id}")
        ref = task.reference
        denom = max(len(ref), 1)
        return {"cer": _edit_distance(prediction, ref) / denom}


def scorer() -> _Scorer:
    return _Scorer()


def default_instruction() -> str:
    return (
        "You are an expert in OCR post-correction. Correct the OCR errors in "
        "the given text. Do not translate; do not alter names."
    )


def info() -> DatasetInfo:
    return DatasetInfo(
        name="tiny",
        version="0.1",
        splits=_SPLITS,
        notes=(
            "契约夹具数据集：手写样本，cER 为简易字符错误率口径，"
            "不与任何官方成绩可比；t3 为 masked 样例。"
            "loader key 命名：`<subset>/<language>/<granularity>`（tiny/en/unit）。"
        ),
    )
