"""datasets：HIPE-OCRepair jsonl -> Sample；track-unit / track-doc 两轨装载。

对应 Docs/Design/08-eval-framework.md「数据」节。

- track-unit：每行一个 Sample，sample_id = ``{document_id}#{行号}``（行号 1 起）。
- track-doc：按文件内顺序把连续相同 ``document_id`` 的行以 ``"\\n"`` 拼接为
  单条 Sample，sample_id = document_id；gold 同规则拼接；
  ``unit_boundaries`` 记录各组成单元在拼接后文本中的起始字符偏移，
  供 ref 臂（ref-blocr@unit-pieces）切回单元。
- masked-test（ground_truth.transcription_unit 为空串）的行不用于出数：
  整文件 gold 全空时跳过该文件并告警；文件内个别空 gold 行同样跳过并告警。
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ir import Attrs

__all__ = ["Sample", "load_samples"]

DOC_SEPARATOR = "\n"
"""track-doc 拼接分隔符。"""


@dataclass(frozen=True)
class Sample:
    """一条待修复样本（track-unit 单单元 / track-doc 拼接文档）。"""

    sample_id: str
    track: Literal["unit", "doc"]
    language: str
    source_subset: str
    """来源子集（document_metadata.primary_dataset_name），供报告分层。"""
    ocr_text: str
    gold_text: str
    metadata: Attrs = field(default_factory=dict)
    """原始 document_metadata 整字段。"""
    unit_boundaries: tuple[int, ...] = (0,)
    """track-doc 拼接后各组成单元的起始字符偏移（供 ref 臂切回）；unit 轨为 (0,)。"""

    def split_units(self) -> tuple[str, ...]:
        """按 unit_boundaries 把 ocr_text 切回组成单元（去掉单元间分隔符）。"""
        bounds = self.unit_boundaries
        units: list[str] = []
        for i, start in enumerate(bounds):
            if i + 1 < len(bounds):
                end = bounds[i + 1] - len(DOC_SEPARATOR)
            else:
                end = len(self.ocr_text)
            units.append(self.ocr_text[start:end])
        return tuple(units)


def _subset_of(metadata: Attrs) -> str:
    value = metadata.get("primary_dataset_name")
    return value if isinstance(value, str) and value else "unknown"


def _language_of(metadata: Attrs) -> str:
    value = metadata.get("language")
    return value if isinstance(value, str) and value else "unknown"


def _read_rows(path: Path) -> list[tuple[int, dict]]:
    """读 jsonl -> [(行号（1 起）, 记录)]；跳过空白行。"""
    rows: list[tuple[int, dict]] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            rows.append((lineno, json.loads(line)))
    return rows


def _load_unit(rows: list[tuple[int, dict]]) -> tuple[Sample, ...]:
    samples: list[Sample] = []
    for lineno, row in rows:
        metadata: Attrs = dict(row.get("document_metadata") or {})
        document_id = str(metadata.get("document_id", f"row{lineno}"))
        samples.append(
            Sample(
                sample_id=f"{document_id}#{lineno}",
                track="unit",
                language=_language_of(metadata),
                source_subset=_subset_of(metadata),
                ocr_text=row["ocr_hypothesis"]["transcription_unit"],
                gold_text=row["ground_truth"]["transcription_unit"],
                metadata=metadata,
                unit_boundaries=(0,),
            )
        )
    return tuple(samples)


def _load_doc(rows: list[tuple[int, dict]]) -> tuple[Sample, ...]:
    """连续相同 document_id 的行拼接为一个 Sample（保持文件内顺序）。"""
    samples: list[Sample] = []
    group: list[tuple[int, dict]] = []

    def flush() -> None:
        if not group:
            return
        first = group[0][1]
        metadata: Attrs = dict(first.get("document_metadata") or {})
        document_id = str(metadata.get("document_id", f"row{group[0][0]}"))
        ocr_units = [r["ocr_hypothesis"]["transcription_unit"] for _, r in group]
        gold_units = [r["ground_truth"]["transcription_unit"] for _, r in group]
        boundaries: list[int] = []
        offset = 0
        for unit in ocr_units:
            boundaries.append(offset)
            offset += len(unit) + len(DOC_SEPARATOR)
        samples.append(
            Sample(
                sample_id=document_id,
                track="doc",
                language=_language_of(metadata),
                source_subset=_subset_of(metadata),
                ocr_text=DOC_SEPARATOR.join(ocr_units),
                gold_text=DOC_SEPARATOR.join(gold_units),
                metadata=metadata,
                unit_boundaries=tuple(boundaries),
            )
        )

    prev_id: object = object()
    for lineno, row in rows:
        document_id = (row.get("document_metadata") or {}).get("document_id")
        if group and document_id != prev_id:
            flush()
            group = []
        group.append((lineno, row))
        prev_id = document_id
    flush()
    return tuple(samples)


def load_samples(path: Path, track: Literal["unit", "doc"]) -> tuple[Sample, ...]:
    """从 jsonl 装载样本。

    masked-test（gold 为空串）处理：整文件 gold 全空 -> 跳过整文件并告警；
    文件内个别空 gold 行 -> 跳过该行并告警（masked 行不出数）。
    """
    path = Path(path)
    rows = _read_rows(path)
    if not rows:
        warnings.warn(f"{path}: 空文件，无样本可装载", stacklevel=2)
        return ()

    kept: list[tuple[int, dict]] = []
    masked = 0
    for lineno, row in rows:
        gold = (row.get("ground_truth") or {}).get("transcription_unit")
        if not gold:
            masked += 1
            continue
        kept.append((lineno, row))

    if masked == len(rows):
        warnings.warn(
            f"{path}: 全部 {masked} 行 gold 为空（masked-test），跳过该文件",
            stacklevel=2,
        )
        return ()
    if masked:
        warnings.warn(
            f"{path}: 跳过 {masked} 行 gold 为空的 masked 记录", stacklevel=2
        )

    if track == "unit":
        return _load_unit(kept)
    if track == "doc":
        return _load_doc(kept)
    raise ValueError(f"unknown track: {track!r}")
