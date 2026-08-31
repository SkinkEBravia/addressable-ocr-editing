"""IR 出生接口：PartitionResult -> DocumentSnapshot。

对应 Docs/Design/05-ir-io.md「出生接口」节。

解耦约定：不 import sourceio / partition，用 typing.Protocol 定义结构性
输入——任何带有相应字段的对象都可作为 source / result。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol, Sequence, runtime_checkable

from .types import Attrs, Block, DocumentSnapshot, snapshot_id

SOURCE_DOC_ATTR_KEY = "source"
"""doc_attrs 中的保留键：记录来源文本的编码与 BOM，partition 实现不得使用。"""


class PartitionError(Exception):
    """出生校验失败：块序列不满足严格分区契约，或保留了键被占用。"""


@runtime_checkable
class SourceLike(Protocol):
    """结构性输入：sourceio.SourceText 的鸭子类型。"""

    text: str
    encoding: str
    bom: bytes


@runtime_checkable
class BlockDraftLike(Protocol):
    """结构性输入：partition.BlockDraft 的鸭子类型（content + attrs，无 key）。"""

    content: str
    attrs: Attrs


@runtime_checkable
class PartitionResultLike(Protocol):
    """结构性输入：partition.PartitionResult 的鸭子类型。"""

    blocks: Sequence[BlockDraftLike]
    doc_attrs: Attrs


def birth(source: SourceLike, result: PartitionResultLike) -> DocumentSnapshot:
    """PartitionResult -> DocumentSnapshot。

    1. 校验契约：concat(d.content for d in result.blocks) == source.text，
       不符抛 PartitionError（严格分区的验收点在边界，而非信任上游）。
    2. 装订 key：key_cursor 从 1 起，按序为每个块坯分配 b{cursor}。
    3. result.doc_attrs 原样进入快照 doc_attrs；另写入保留键
       "source": {"encoding": ..., "bom": <hex str>}（无 BOM 为空串）。
    4. 生成 SnapshotId。
    """
    drafts = list(result.blocks)
    concat = "".join(d.content for d in drafts)
    if concat != source.text:
        raise PartitionError(
            "strict partition violated: "
            f"concat(blocks) has {len(concat)} chars, "
            f"source.text has {len(source.text)} chars"
        )

    doc_attrs: Attrs = dict(result.doc_attrs)
    if SOURCE_DOC_ATTR_KEY in doc_attrs:
        raise PartitionError(
            f"doc_attrs uses reserved key {SOURCE_DOC_ATTR_KEY!r}"
        )
    doc_attrs[SOURCE_DOC_ATTR_KEY] = {
        "encoding": source.encoding,
        "bom": bytes(source.bom).hex(),
    }

    blocks: list[Block] = []
    cursor = 1
    for draft in drafts:
        blocks.append(
            Block(key=f"b{cursor}", content=draft.content, attrs=dict(draft.attrs))
        )
        cursor += 1

    snapshot = DocumentSnapshot(
        id="",
        blocks=tuple(blocks),
        doc_attrs=doc_attrs,
        key_cursor=cursor,
    )
    return replace(snapshot, id=snapshot_id(snapshot))
