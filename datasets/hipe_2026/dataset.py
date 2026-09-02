"""hipe_2026：HIPE-OCRepair-2026 数据集的 dataset.py 契约实现。

契约见 Docs/Design/10-datasets.md。物理布局（related_source/ 下的官方
jsonl 目录树）完全隔离在本文件内部；OCR 与 gold 在官方记录内分字段存放。

最小读取单位 = chunk（一行 jsonl = 一页/一条转写单元）。loader 注册表覆盖
子集 × 语言 × 粒度，key 形如 `<subset>/<language>/<granularity>`：

    icdar2017/en/chunk   icdar2017/en/doc
    dta19-l0/de/chunk    dta19-l0/de/doc   ...

- chunk：逐转写单元，与官方可比；
- doc：同源文档的 chunk 按页/序号拼接（自设口径，不与官方排名可比）。
  doc 分组键 = 源文档：dta19 剥 document_id 的 `_lX_pYYY` 后缀；
  icdar2017 从 primary_dataset_filename 解析（其 document_id 每行唯一）；
  其余子集（impresso-nzz / impresso-snippets / overproof）每条即独立文档，
  doc ≡ chunk。doc 得分 = chunk 均值 + 方差（见 scorer）。
- subset 取自 jsonl 文件名（dta19 含退化级，如 dta19-l0）；language 取自目录。

split: train / dev / test / masked-test（masked 的 reference=None，不出数；
官方 `*-unmatched` 文件为对齐失败行，不纳入装载）。
default_instruction: BLOCR SYSTEM_PROMPT 的指令体逐字副本（instruction.md）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from datasetkit import DatasetInfo, Loader, ScoreError, Task

_DIR = Path(__file__).resolve().parent
_DATA_ROOT = (
    _DIR.parent.parent / "related_source" / "HIPE-OCRepair-2026-data-0.9.5" / "data" / "v0.9"
)

DOC_SEPARATOR = "\n"
"""granularity='doc' 的单元拼接分隔符。"""

__all__ = ["loaders", "scorer", "score_all", "default_instruction", "info"]

_SPLITS = ("train", "dev", "test", "masked-test")


# ---------------------------------------------------------------------------
# 装载（物理布局隔离于此）：最小读取单位 = chunk
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Chunk:
    """一行 jsonl = 一个 chunk。doc 粒度是 _Chunk 序列上的分组视图。"""

    subset: str  # dta19-l0 / icdar2017 / ...
    language: str  # de / en / fr
    document: str  # 源文档键（subset 内唯一）
    label: str  # chunk 在文档内的标识（p025 / chunk_100 / document_id）
    order: tuple  # 文档内排序键
    ocr: str
    gold: str | None  # None = masked
    meta: dict = field(default_factory=dict)


def _split_files(split: str) -> list[Path]:
    # `*_{split}_*.jsonl` 不匹配 `dev-unmatched`（分隔符不同）：对齐失败行不纳入
    return sorted(_DATA_ROOT.glob(f"*/*/*_{split}_*.jsonl"))


def _subset_of(path: Path) -> str:
    # hipe-ocrepair-bench_v0.9_<subset>_<ver>_<split>_<lang>.jsonl（subset 无下划线）
    return path.stem.split("_")[2]


_DTA19_ID = re.compile(r"(.+)_l\d+_p(\d+)$")
_ICDAR_DOC = re.compile(r"icdar2017__(?:train|test)__(?:en|fr|de)__(.+)__chunk_")
_ICDAR_CHUNK = re.compile(r"__chunk_(\d+)(?:-([a-z]))?__GT\.txt$")


def _document_key(subset: str, document_id: str, filename: str, lineno: int) -> tuple[str, str, tuple]:
    """（document, label, order）：源文档分组键 + chunk 标识 + 文档内排序键。"""
    if subset.startswith("dta19"):
        m = _DTA19_ID.fullmatch(document_id)
        if m:
            return m.group(1), f"p{m.group(2)}", (int(m.group(2)),)
    elif subset == "icdar2017":
        base = filename.rsplit("/", 1)[-1]
        doc = _ICDAR_DOC.search(base)
        chunk = _ICDAR_CHUNK.search(base)
        if doc and chunk:
            return (
                doc.group(1),
                f"chunk_{chunk.group(1)}{'-' + chunk.group(2) if chunk.group(2) else ''}",
                (int(chunk.group(1)), chunk.group(2) or ""),
            )
    # impresso-nzz / impresso-snippets / overproof：每条即独立文档（doc ≡ chunk）
    return document_id, document_id, (lineno,)


def _iter_chunks(path: Path, masked: bool) -> Iterable[_Chunk]:
    subset = _subset_of(path)
    language = path.parent.name
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            gold = (row.get("ground_truth") or {}).get("transcription_unit")
            if not masked and not gold:
                continue  # gold 为空的行（对齐失败/masked 混入）不出数：跳过
            meta = dict(row.get("document_metadata") or {})
            document_id = str(meta.get("document_id", f"row{lineno}"))
            document, label, order = _document_key(
                subset, document_id, str(meta.get("primary_dataset_filename") or ""), lineno
            )
            yield _Chunk(
                subset=subset,
                language=language,
                document=document,
                label=label,
                order=order,
                ocr=row["ocr_hypothesis"]["transcription_unit"],
                gold=None if masked else gold,
                meta={
                    **meta,
                    "subset": subset,
                    "language": language,
                    "document": document,
                    "source_file": path.name,
                    "row": lineno,
                },
            )


def _chunk_task(chunk: _Chunk) -> Task:
    return Task(
        task_id=f"{chunk.subset}/{chunk.document}#{chunk.label}",
        input=chunk.ocr,
        reference=chunk.gold,
        meta=chunk.meta,
    )


def _doc_task(chunks: list[_Chunk]) -> Task:
    """同源文档的 chunk 按 order 拼接；meta 带 gold_units / unit_boundaries 供评分与切回。"""
    chunks = sorted(chunks, key=lambda c: c.order)
    first = chunks[0]
    boundaries: list[int] = []
    offset = 0
    for c in chunks:
        boundaries.append(offset)
        offset += len(c.ocr) + len(DOC_SEPARATOR)
    meta = {
        **{k: v for k, v in first.meta.items() if k != "row"},
        "n_chunks": len(chunks),
        "unit_boundaries": boundaries,  # OCR 侧各单元起始偏移（供 rewrite_pieces 切回）
        "gold_units": [c.gold or "" for c in chunks],  # gold 侧逐单元（供 doc 评分拆回）
    }
    return Task(
        task_id=f"{first.subset}/{first.document}",
        input=DOC_SEPARATOR.join(c.ocr for c in chunks),
        reference=None if first.gold is None else DOC_SEPARATOR.join(c.gold or "" for c in chunks),
        meta=meta,
    )


def _tasks_from_file(path: Path, granularity: str, masked: bool) -> list[Task]:
    chunks = list(_iter_chunks(path, masked))
    if granularity == "chunk":
        return [_chunk_task(c) for c in chunks]
    groups: dict[tuple[str, str], list[_Chunk]] = {}
    for c in chunks:
        groups.setdefault((c.subset, c.document), []).append(c)
    return [_doc_task(g) for _, g in sorted(groups.items())]


# ---------------------------------------------------------------------------
# 契约入口
# ---------------------------------------------------------------------------

def loaders(*, split: str) -> dict[str, Loader]:
    """loader 注册表：`<subset>/<language>/<granularity>` -> 零参 Task 流。"""
    if split not in _SPLITS:
        raise ValueError(f"未知 split {split!r}（{_SPLITS}）")
    masked = split == "masked-test"
    out: dict[str, Loader] = {}
    for path in _split_files(split):
        key_prefix = f"{_subset_of(path)}/{path.parent.name}"
        for granularity in ("chunk", "doc"):
            out[f"{key_prefix}/{granularity}"] = (
                lambda p=path, g=granularity, m=masked: _tasks_from_file(p, g, m)
            )
    return out


# ---------------------------------------------------------------------------
# 评分（官方归一化 + MER；聚合口径见 score_all）
# ---------------------------------------------------------------------------

def _record(task: Task, output: str) -> dict:
    meta = {
        k: v
        for k, v in task.meta.items()
        if k not in ("unit_boundaries", "gold_units", "n_chunks")
    }
    meta["document_id"] = task.task_id
    return {
        "document_metadata": meta,
        "ocr_hypothesis": {"transcription_unit": task.input},
        "ground_truth": {"transcription_unit": task.reference or ""},
        "ocr_postcorrection_output": {"transcription_unit": output},
    }


def _cmer(reference: str, hypothesis: str) -> float:
    """逐条 cMER：官方归一化 + jiwer 字符对齐 + 官方 MER 公式。"""
    from hipe_ocrepair_scorer.ocrepair_eval import mer_from_counts, norm
    from jiwer import process_characters

    out = process_characters(norm(reference), norm(hypothesis))
    return mer_from_counts(out.hits, out.substitutions, out.deletions, out.insertions)


class _Scorer:
    def score(self, prediction: str, task: Task) -> dict[str, float]:
        if task.reference is None:
            raise ScoreError(f"masked task 不出数: {task.task_id}")
        gold_units = task.meta.get("gold_units")
        if gold_units:  # doc 粒度：得分 = chunk 均值 + 方差（复用逐条评分）
            if len(gold_units) == 1:
                # 单 chunk（doc ≡ chunk 的子集常态）：无需拆分，直接逐条评分
                return {
                    "cmer": _cmer(gold_units[0], prediction),
                    "cmer_var": 0.0,
                    "n_chunks": 1.0,
                    "cmer_hyp": _cmer(gold_units[0], task.input),
                    "chunks_aligned": 1.0,
                }
            pred_chunks = prediction.split(DOC_SEPARATOR)
            if len(pred_chunks) == len(gold_units):
                values = [
                    _cmer(g, p) for g, p in zip(gold_units, pred_chunks)
                ]
                mean = sum(values) / len(values)
                var = sum((v - mean) ** 2 for v in values) / len(values)  # 总体方差
                hyp_values = [
                    _cmer(g, p)
                    for g, p in zip(gold_units, task.input.split(DOC_SEPARATOR))
                ]
                return {
                    "cmer": mean,
                    "cmer_var": var,
                    "n_chunks": float(len(values)),
                    "cmer_hyp": sum(hyp_values) / len(hyp_values),
                    "chunks_aligned": 1.0,
                }
            # 拼接结构被改坏（分隔符数量对不上）：回退整篇口径并标记
            return {
                "cmer": _cmer(task.reference, prediction),
                "cmer_var": 0.0,
                "n_chunks": 1.0,
                "cmer_hyp": _cmer(task.reference, task.input),
                "chunks_aligned": 0.0,
            }
        return {
            "cmer": _cmer(task.reference, prediction),
            "cmer_hyp": _cmer(task.reference, task.input),
        }


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
        notes=(
            "loader key 命名：`<subset>/<language>/<granularity>`"
            "（如 icdar2017/en/chunk、dta19-l0/de/doc）。"
            "口径：chunk 粒度（逐转写单元）与官方成绩可比；doc 粒度（同源文档 "
            "chunk 按页/序号拼接）为自设场景，不与官方排名可比，doc 得分 = chunk "
            "均值 + 方差。doc 分组键 = 源文档：dta19 剥 document_id 的 _lX_pYYY "
            "后缀；icdar2017 从 primary_dataset_filename 解析（其 document_id "
            "每行唯一）；impresso-nzz / impresso-snippets / overproof 每条即独立"
            "文档，doc ≡ chunk。官方 *-unmatched 文件（对齐失败行）不纳入装载。"
            "评分前归一化抹除换行/标点/大小写差异，字节级保真优势"
            "不计分。no-correction 基线很强，noop 是必设锚点。masked-test 的 GT 为空，"
            "不出数。"
        ),
    )
