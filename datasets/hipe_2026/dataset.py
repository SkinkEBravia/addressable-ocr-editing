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


def _decompose_alignment(reference: str, ocr: str, hypothesis: str) -> dict[str, float]:
    """计算细粒度分解指标：fixed_rate, broken_rate, halluc_ins, missed_rate。

    对应 Docs/HIPE-metrics-decomposition.md。
    """
    from hipe_ocrepair_scorer.ocrepair_eval import norm
    from jiwer import process_characters

    norm_g = norm(reference)
    norm_i = norm(ocr)
    norm_h = norm(hypothesis)
    n_g = len(norm_g)

    align_i = process_characters(norm_g, norm_i)
    align_h = process_characters(norm_g, norm_h)

    status_i = [None] * n_g
    status_h = [None] * n_g
    ins_i = [0] * (n_g + 1)
    ins_h = [0] * (n_g + 1)

    if align_i.alignments:
        for chunk in align_i.alignments[0]:
            if chunk.type == "insert":
                ins_i[chunk.ref_start_idx] += (chunk.hyp_end_idx - chunk.hyp_start_idx)
            else:
                for idx in range(chunk.ref_start_idx, chunk.ref_end_idx):
                    status_i[idx] = chunk.type

    if align_h.alignments:
        for chunk in align_h.alignments[0]:
            if chunk.type == "insert":
                ins_h[chunk.ref_start_idx] += (chunk.hyp_end_idx - chunk.hyp_start_idx)
            else:
                for idx in range(chunk.ref_start_idx, chunk.ref_end_idx):
                    status_h[idx] = chunk.type

    fixed_sub = fixed_del = 0
    broken_sub = broken_del = 0
    missed_sub = missed_del = 0
    i_missing_at = [0] * (n_g + 1)

    for idx in range(n_g):
        s_i = status_i[idx]
        s_h = status_h[idx]
        i_ok = (s_i == "equal")
        h_ok = (s_h == "equal")

        if s_i == "delete":
            i_missing_at[idx] += 1

        if i_ok and not h_ok:
            if s_h == "substitute":
                broken_sub += 1
            else:
                broken_del += 1
        elif not i_ok and h_ok:
            if s_i == "substitute":
                fixed_sub += 1
            else:
                fixed_del += 1
        elif not i_ok and not h_ok:
            if s_i == "substitute":
                missed_sub += 1
            else:
                missed_del += 1

    fixed_ins_del = 0
    missed_ins = 0
    broken_ins = 0

    for idx in range(n_g + 1):
        num_i = ins_i[idx]
        num_h = ins_h[idx]

        # 原文自带的多余插入字符：保留算欠修，删除算修复
        missed_ins += min(num_i, num_h)
        fixed_ins_del += max(0, num_i - num_h)

        # 模型相对原文主动新增的多余插入字符：全部属于模型引入的幻觉
        broken_ins += max(0, num_h - num_i)

    fixed = fixed_sub + fixed_del + fixed_ins_del
    broken = broken_sub + broken_del + broken_ins
    missed = missed_sub + missed_del + missed_ins

    errors_i = align_i.substitutions + align_i.deletions + align_i.insertions
    correct_i = align_i.hits

    fixed_rate = fixed / errors_i if errors_i > 0 else 0.0
    missed_rate = missed / errors_i if errors_i > 0 else 0.0
    broken_rate = broken / correct_i if correct_i > 0 else 0.0
    denom_halluc = n_g + align_h.insertions
    halluc_ins = broken_ins / denom_halluc if denom_halluc > 0 else 0.0

    return {
        "fixed_rate": fixed_rate,
        "broken_rate": broken_rate,
        "halluc_ins": halluc_ins,
        "missed_rate": missed_rate,
    }


def _score_unit(reference: str, ocr: str, hypothesis: str) -> dict[str, float]:
    """逐转写单元评分：cmer + cmer_hyp + 四维分解指标。"""
    cmer = _cmer(reference, hypothesis)
    cmer_hyp = _cmer(reference, ocr)
    decomp = _decompose_alignment(reference, ocr, hypothesis)
    return {
        "cmer": cmer,
        "cmer_hyp": cmer_hyp,
        **decomp,
    }


class _Scorer:
    def score(self, prediction: str, task: Task) -> dict[str, float]:
        if task.reference is None:
            raise ScoreError(f"masked task 不出数: {task.task_id}")
        gold_units = task.meta.get("gold_units")
        if gold_units:  # doc 粒度：得分 = chunk 均值 + 方差（复用逐条评分）
            ocr_chunks = task.input.split(DOC_SEPARATOR)
            if len(gold_units) == 1:
                # 单 chunk（doc ≡ chunk 的子集常态）：无需拆分，直接逐条评分
                ocr_text = ocr_chunks[0] if ocr_chunks else task.input
                unit_res = _score_unit(gold_units[0], ocr_text, prediction)
                return {
                    **unit_res,
                    "cmer_var": 0.0,
                    "n_chunks": 1.0,
                    "chunks_aligned": 1.0,
                }
            pred_chunks = prediction.split(DOC_SEPARATOR)
            if len(pred_chunks) == len(gold_units) and len(ocr_chunks) == len(gold_units):
                chunk_scores = [
                    _score_unit(g, o, p)
                    for g, o, p in zip(gold_units, ocr_chunks, pred_chunks)
                ]
                agg = {
                    key: sum(cs[key] for cs in chunk_scores) / len(chunk_scores)
                    for key in chunk_scores[0]
                }
                cmer_values = [cs["cmer"] for cs in chunk_scores]
                mean_cmer = agg["cmer"]
                var_cmer = sum((v - mean_cmer) ** 2 for v in cmer_values) / len(cmer_values)
                return {
                    **agg,
                    "cmer_var": var_cmer,
                    "n_chunks": float(len(chunk_scores)),
                    "chunks_aligned": 1.0,
                }
            # 拼接结构被改坏（分隔符数量对不上）：回退整篇口径并标记
            whole_res = _score_unit(task.reference, task.input, prediction)
            return {
                **whole_res,
                "cmer_var": 0.0,
                "n_chunks": 1.0,
                "chunks_aligned": 0.0,
            }
        return _score_unit(task.reference, task.input, prediction)


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
