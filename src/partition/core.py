"""块生成（Partition）：SourceText -> tuple[BlockDraft, ...] + 文档级 attrs。

不分配 BlockKey，不感知 IR；只对本模块定义的输出契约（严格分区）负责。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

__all__ = [
    "JsonValue",
    "Attrs",
    "TextSource",
    "BlockDraft",
    "PartitionResult",
    "partition_chars",
    "partition_lines",
    "to_json",
    "from_json",
]

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
"""全系统元数据的统一值类型（JSON 可序列化）。"""

type Attrs = dict[str, JsonValue]
"""块级 / 文档级元数据的统一载体。"""


class TextSource(Protocol):
    """结构性输入：partition 只读取 ``.text``，不依赖 sourceio。"""

    text: str


@dataclass(frozen=True)
class BlockDraft:
    """无 key 的块坯。Block = BlockKey + BlockDraft。"""

    content: str
    attrs: Attrs = field(default_factory=dict)


@dataclass(frozen=True)
class PartitionResult:
    """partition 的输出：有序块序列 + 文档级元数据。

    契约（严格分区）：``concat(d.content for d in blocks) == source.text``，
    空文本对应空 ``blocks``（唯一例外）。
    """

    blocks: tuple[BlockDraft, ...]
    doc_attrs: Attrs = field(default_factory=dict)


def partition_chars(source: TextSource, size: int) -> PartitionResult:
    """参考实现：每 ``size`` 个字符切一块，最后一块允许短于 ``size``。

    - 每块 attrs：``{"start": <int>}``，该块在全文中的起始字符偏移。
    - doc_attrs：``{"partition": "chars", "size": size}``。
    - 空文本 -> 空 blocks。
    """
    if size < 1:
        raise ValueError(f"size must be a positive integer, got {size}")

    text = source.text
    blocks = tuple(
        BlockDraft(content=text[start : start + size], attrs={"start": start})
        for start in range(0, len(text), size)
    )
    return PartitionResult(blocks=blocks, doc_attrs={"partition": "chars", "size": size})


def partition_lines(source: TextSource) -> PartitionResult:
    """参考实现：按行切分（``str.splitlines(keepends=True)`` 语义），行终止符归属其所在块。

    - 每块 attrs：``{"start": <int>, "line": <int>}``，分别为起始字符偏移与 0 起的行号。
    - doc_attrs：``{"partition": "lines"}``。
    - 空文本 -> 空 blocks。
    """
    blocks: list[BlockDraft] = []
    offset = 0
    for n, line in enumerate(source.text.splitlines(keepends=True)):
        blocks.append(BlockDraft(content=line, attrs={"start": offset, "line": n}))
        offset += len(line)
    return PartitionResult(blocks=tuple(blocks), doc_attrs={"partition": "lines"})


def to_json(result: PartitionResult) -> str:
    """PartitionResult -> JSON 字符串。全体成员均为 str / JsonValue，无需自定义编码器。"""
    return json.dumps(
        {
            "blocks": [{"content": b.content, "attrs": b.attrs} for b in result.blocks],
            "doc_attrs": result.doc_attrs,
        },
        ensure_ascii=False,
    )


def from_json(payload: str) -> PartitionResult:
    """JSON 字符串 -> PartitionResult，与 ``to_json`` 往返无损。"""
    data = json.loads(payload)
    return PartitionResult(
        blocks=tuple(BlockDraft(content=b["content"], attrs=b["attrs"]) for b in data["blocks"]),
        doc_attrs=data["doc_attrs"],
    )
