"""score：官方 scorer（hipe_ocrepair_scorer）适配器。

对应 Docs/Design/08-eval-framework.md「指标 / 修复性能」节：直接调用官方
scorer，不重新实现。主指标 ``cmer_micro``（越小越好），副指标
``pref_score_cmer_macro``（越大越好），沿用其归一化与 bootstrap 95% CI。

- ``write_hyp_jsonl`` / ``write_ref_jsonl``：把 (sample, corrected_text) 写成
  HIPE schema 的 jsonl（document_metadata / ocr_hypothesis / ground_truth /
  ocr_postcorrection_output 四字段）。
- ``score_pairs``：内存中构造记录并评分，返回结构化 dict。
- track-doc 以整文件为一条记录（自设口径，由 datasets 装载决定）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from hipe_ocrepair_scorer import Evaluation, align_records

from experiment_app.datasets import Sample

__all__ = [
    "hyp_record",
    "ref_record",
    "write_hyp_jsonl",
    "write_ref_jsonl",
    "score_pairs",
]


def _base_record(sample: Sample, output_text: str) -> dict:
    """HIPE schema 记录：document_metadata 沿用样本元数据，document_id 用 sample_id。"""
    metadata = dict(sample.metadata)
    metadata["document_id"] = sample.sample_id
    metadata.setdefault("primary_dataset_name", sample.source_subset)
    return {
        "document_metadata": metadata,
        "ocr_hypothesis": {"transcription_unit": sample.ocr_text},
        "ground_truth": {"transcription_unit": sample.gold_text},
        "ocr_postcorrection_output": {"transcription_unit": output_text},
    }


def hyp_record(sample: Sample, corrected_text: str) -> dict:
    """hyp 侧记录：ocr_postcorrection_output = 修复后文本。"""
    return _base_record(sample, corrected_text)


def ref_record(sample: Sample) -> dict:
    """ref 侧记录：与原始样本同格式（ocr_postcorrection_output 置为 gold）。"""
    return _base_record(sample, sample.gold_text)


def _write_jsonl(path: Path, records: Iterable[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_hyp_jsonl(path: Path, pairs: Iterable[tuple[Sample, str]]) -> None:
    """把一组 (sample, corrected_text) 写成 hyp jsonl。"""
    _write_jsonl(path, (hyp_record(sample, text) for sample, text in pairs))


def write_ref_jsonl(path: Path, samples: Iterable[Sample]) -> None:
    """把原始样本写成 ref jsonl（同格式）。"""
    _write_jsonl(path, (ref_record(sample) for sample in samples))


def score_pairs(pairs: Iterable[tuple[Sample, str]]) -> dict:
    """对一组 (sample, corrected_text) 评分。

    返回官方 scorer 的完整结果 dict（``averaged_scores`` / ``fold_scores``，
    每项指标为 (score, lo_ci, hi_ci)）。官方实现内部固定随机种子，
    同一输入的 CI 可复现。
    """
    pairs = tuple(pairs)
    if not pairs:
        raise ValueError("no samples to score")
    ref_records = [ref_record(sample) for sample, _ in pairs]
    hyp_records = [hyp_record(sample, text) for sample, text in pairs]
    merged = align_records(ref_records, hyp_records)
    return Evaluation(merged).score_over_datasets(normalize=True)
