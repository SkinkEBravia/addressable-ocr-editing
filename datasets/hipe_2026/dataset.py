"""hipe_2026：HIPE-OCRepair-2026 数据集的 dataset.py 契约实现。

契约见 Docs/Design/10-datasets.md。物理布局（related_source/ 下的官方
jsonl 目录树）完全隔离在本文件内部；OCR 与 gold 在官方记录内分字段存放。

- split: train / dev / test / masked-test（masked 的 reference=None，不出数）。
- granularity: unit（逐转写单元，与官方可比）| doc（同 document_id 拼接，
  自设口径，不与官方排名可比）。
- scorer: 官方归一化（hipe_ocrepair_scorer.norm）+ jiwer 字符对齐 +
  官方 MER 公式的逐条 cMER；聚合口径（fold/bootstrap CI）由 score_all 给出。
- default_instruction: BLOCR SYSTEM_PROMPT 的指令体逐字副本（instruction.md）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from datasetkit import DatasetInfo, ScoreError, Task

_DIR = Path(__file__).resolve().parent
_DATA_ROOT = (
    _DIR.parent.parent / "related_source" / "HIPE-OCRepair-2026-data-0.9.5" / "data" / "v0.9"
)

DOC_SEPARATOR = "\n"
"""granularity='doc' 的单元拼接分隔符。"""

__all__ = ["tasks", "scorer", "score_all", "default_instruction", "info"]

_SPLITS = ("train", "dev", "test", "masked-test")
_GRANULARITIES = ("unit", "doc")


# ---------------------------------------------------------------------------
# 装载（物理布局隔离于此）
# ---------------------------------------------------------------------------

def _split_files(split: str, languages: list[str] | None) -> list[Path]:
    files = sorted(_DATA_ROOT.glob(f"*/*/*_{split}_*.jsonl"))
    if languages is not None:
        files = [p for p in files if p.parent.name in languages]
    return files


def _read_rows(path: Path) -> list[tuple[int, dict]]:
    rows: list[tuple[int, dict]] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if line:
                rows.append((lineno, json.loads(line)))
    return rows


def _meta_of(row: dict) -> dict[str, Any]:
    return dict(row.get("document_metadata") or {})


def _row_to_unit_task(path: Path, lineno: int, row: dict, masked: bool) -> Task:
    meta = _meta_of(row)
    document_id = str(meta.get("document_id", f"row{lineno}"))
    meta = {**meta, "source_file": path.name, "row": lineno}
    return Task(
        task_id=f"{document_id}#{lineno}",
        input=row["ocr_hypothesis"]["transcription_unit"],
        reference=None if masked else row["ground_truth"]["transcription_unit"],
        meta=meta,
    )


def _group_to_doc_task(path: Path, group: list[tuple[int, dict]], masked: bool) -> Task:
    meta = _meta_of(group[0][1])
    document_id = str(meta.get("document_id", f"row{group[0][0]}"))
    ocr_units = [r["ocr_hypothesis"]["transcription_unit"] for _, r in group]
    gold_units = [r["ground_truth"]["transcription_unit"] for _, r in group]
    boundaries: list[int] = []
    offset = 0
    for unit in ocr_units:
        boundaries.append(offset)
        offset += len(unit) + len(DOC_SEPARATOR)
    meta = {
        **meta,
        "source_file": path.name,
        "unit_boundaries": boundaries,  # 供 rewrite_pieces 切回单元
    }
    return Task(
        task_id=document_id,
        input=DOC_SEPARATOR.join(ocr_units),
        reference=None if masked else DOC_SEPARATOR.join(gold_units),
        meta=meta,
    )


def _load_file(
    path: Path, granularity: str, masked: bool
) -> Iterable[Task]:
    rows = _read_rows(path)
    if not masked:
        # masked 行（gold 为空串）不出数：逐行跳过
        rows = [
            (ln, r)
            for ln, r in rows
            if (r.get("ground_truth") or {}).get("transcription_unit")
        ]
    if granularity == "unit":
        for lineno, row in rows:
            yield _row_to_unit_task(path, lineno, row, masked)
        return
    # doc：连续相同 document_id 的行按文件内顺序拼接
    group: list[tuple[int, dict]] = []
    prev_id: Any = object()

    def flush() -> Task | None:
        nonlocal group
        if not group:
            return None
        task = _group_to_doc_task(path, group, masked)
        group = []
        return task

    for lineno, row in rows:
        document_id = _meta_of(row).get("document_id")
        if group and document_id != prev_id:
            task = flush()
            if task is not None:
                yield task
        group.append((lineno, row))
        prev_id = document_id
    task = flush()
    if task is not None:
        yield task


def tasks(
    *,
    split: str,
    granularity: str | None = None,
    ids: list[str] | None = None,
    languages: list[str] | None = None,
    limit: int | None = None,
) -> list[Task]:
    if split not in _SPLITS:
        raise ValueError(f"未知 split {split!r}（{_SPLITS}）")
    granularity = granularity or "unit"
    if granularity not in _GRANULARITIES:
        raise ValueError(f"未知 granularity {granularity!r}（{_GRANULARITIES}）")
    masked = split == "masked-test"
    out: list[Task] = []
    for path in _split_files(split, languages):
        for task in _load_file(path, granularity, masked):
            if ids is not None and task.task_id not in ids:
                continue
            out.append(task)
    if limit is not None:
        out = out[:limit]
    return out


# ---------------------------------------------------------------------------
# 评分（官方归一化 + MER；聚合口径见 score_all）
# ---------------------------------------------------------------------------

def _record(task: Task, output: str) -> dict:
    meta = {k: v for k, v in task.meta.items() if k != "unit_boundaries"}
    meta["document_id"] = task.task_id
    return {
        "document_metadata": meta,
        "ocr_hypothesis": {"transcription_unit": task.input},
        "ground_truth": {"transcription_unit": task.reference or ""},
        "ocr_postcorrection_output": {"transcription_unit": output},
    }


class _Scorer:
    def score(self, prediction: str, task: Task) -> dict[str, float]:
        if task.reference is None:
            raise ScoreError(f"masked task 不出数: {task.task_id}")
        from hipe_ocrepair_scorer.ocrepair_eval import mer_from_counts, norm
        from jiwer import process_characters

        out = process_characters(norm(task.reference), norm(prediction))
        cmer = mer_from_counts(out.hits, out.substitutions, out.deletions, out.insertions)
        base = process_characters(norm(task.reference), norm(task.input))
        cmer_hyp = mer_from_counts(
            base.hits, base.substitutions, base.deletions, base.insertions
        )
        return {"cmer": cmer, "cmer_hyp": cmer_hyp}


def scorer() -> _Scorer:
    return _Scorer()


def score_all(pairs: Iterable[tuple[Task, str]]) -> dict:
    """聚合口径：官方 Evaluation（fold 分层 + bootstrap 95% CI）。

    pairs = (task, corrected_text)；masked task 不允许传入。
    """
    from hipe_ocrepair_scorer.ocrepair_eval import Evaluation, align_records

    pairs = tuple(pairs)
    if not pairs:
        raise ScoreError("no tasks to score")
    for task, _ in pairs:
        if task.reference is None:
            raise ScoreError(f"masked task 不出数: {task.task_id}")
    ref_records = [_record(task, task.reference or "") for task, _ in pairs]
    hyp_records = [_record(task, text) for task, text in pairs]
    merged = align_records(ref_records, hyp_records)
    return Evaluation(merged).score_over_datasets(normalize=True)


def default_instruction() -> str:
    return (_DIR / "instruction.md").read_text(encoding="utf-8")


def info() -> DatasetInfo:
    return DatasetInfo(
        name="hipe_2026",
        version="0.9.5",
        splits=_SPLITS,
        granularities=_GRANULARITIES,
        notes=(
            "口径：unit 粒度与官方成绩可比；doc 粒度（同 document_id 拼接）为自设场景，"
            "不与官方排名可比。评分前归一化抹除换行/标点/大小写差异，字节级保真优势"
            "不计分。no-correction 基线很强，noop 是必设锚点。masked-test 的 GT 为空，"
            "不出数。"
        ),
    )
