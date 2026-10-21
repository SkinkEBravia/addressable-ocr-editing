"""IR 状态迁移：Op 封闭集合、apply 纯函数与 OpError。

对应 Docs/Design/04-ir-ops.md。

- apply 是纯函数：批次按序应用、原子——任一 op 失败抛 OpError，
  不产生新快照，原快照不变；空批次返回原快照（同一对象）。
- 非空批次成功时产出结果快照；ID 由状态决定，只有 Append 推进游标。
- RollBack 不是 Op；其物理实现是 store 的 set_current（见 05 / store.py）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .birth import BlockDraftLike
from .types import (
    HEAD,
    Attrs,
    Block,
    BlockKey,
    DocumentSnapshot,
    alloc,
    snapshot_id,
)

# 原因码（机器可判读）
KEY_NOT_FOUND = "KEY_NOT_FOUND"
"""op 指向的 key 不是当前快照中任何真实块的 key。"""

BAD_ANCHOR = "BAD_ANCHOR"
"""Append 的锚点既不是 HEAD，也不是当前快照中存在的 key。"""

ANCHOR_IS_REMOVED = "ANCHOR_IS_REMOVED"
"""缺失锚点符合 bN 且编号小于当前游标时的错误分类，不查询历史。"""


# ---------------------------------------------------------------------------
# Op：封闭集合，无其他迁移方式
# ---------------------------------------------------------------------------

class Op:
    """迁移操作的基类（tagged union 的 tag）。"""

    __slots__ = ()


@dataclass(frozen=True)
class Append(Op):
    """把块坯（content + attrs，无 key）插到锚点之后。

    at = HEAD 表示插到最前；锚点为末块即尾部追加。
    key 由分配器在 apply 时装订。
    """

    draft: BlockDraftLike
    at: BlockKey = HEAD


@dataclass(frozen=True)
class Remove(Op):
    """移除 key 对应的块；不回收编号，恢复旧快照时仍会恢复旧游标。"""

    key: BlockKey


@dataclass(frozen=True)
class SetContent(Op):
    """整体替换块的 content。"""

    key: BlockKey
    content: str


@dataclass(frozen=True)
class SetAttrs(Op):
    """整体替换块的 attrs（合并归调用方负责）。"""

    key: BlockKey
    attrs: Attrs


@dataclass(frozen=True)
class OpError(Exception):
    """apply 失败的全部信息，供上层定位与包装。"""

    index: int
    """失败 op 在批次内的序号。"""
    op: Op
    """失败的那条 op。"""
    reason: str
    """KEY_NOT_FOUND / BAD_ANCHOR / ANCHOR_IS_REMOVED 等机器可判读的原因码。"""
    key: BlockKey | None = None
    """涉及的 key（如有）。"""

    def __str__(self) -> str:
        return (
            f"op[{self.index}] {self.op!r} failed: {self.reason}"
            + (f" (key={self.key!r})" if self.key is not None else "")
        )


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

_ALLOCATED_KEY = re.compile(r"b(\d+)\Z")


def _is_retired_key(key: BlockKey, key_cursor: int) -> bool:
    """缺失 key 符合 bN 且编号小于游标时，归为已移除锚点。

    注意：分配策略可整体替换，调用方不得解析 key 的内容；此判定是
    分配器自身（ir 内部）为错误分类而做的，属于策略实现的一部分。
    """
    m = _ALLOCATED_KEY.match(key)
    return m is not None and int(m.group(1)) < key_cursor


def apply(snapshot: DocumentSnapshot, ops: tuple[Op, ...]) -> DocumentSnapshot:
    """把一批 op 按序、原子地应用到快照上，产出新快照。

    - ops 为空：返回原快照（同一对象），不产出新 SnapshotId。
    - 任一 op 失败：抛 OpError（index 指向失败条），不产生新快照，原快照不变。
    - 成功：返回结果快照；完整状态相同则 ID 相同，只有 Append 推进游标。
    """
    if not ops:
        return snapshot

    blocks = list(snapshot.blocks)
    cursor = snapshot.key_cursor
    positions = {b.key: i for i, b in enumerate(blocks)}

    def rebuild_positions() -> None:
        positions.clear()
        positions.update({b.key: i for i, b in enumerate(blocks)})

    for index, op in enumerate(ops):
        match op:
            case Append(draft=draft, at=anchor):
                if anchor == HEAD:
                    pos = 0
                elif anchor in positions:
                    pos = positions[anchor] + 1
                else:
                    reason = (
                        ANCHOR_IS_REMOVED
                        if _is_retired_key(anchor, cursor)
                        else BAD_ANCHOR
                    )
                    raise OpError(index=index, op=op, reason=reason, key=anchor)
                working = DocumentSnapshot(
                    id="", blocks=(), doc_attrs={}, key_cursor=cursor
                )
                key, cursor = alloc(working)
                blocks.insert(pos, Block(key=key, content=draft.content, attrs=dict(draft.attrs)))
                rebuild_positions()
            case Remove(key=key):
                pos = positions.get(key)
                if key == HEAD or pos is None:
                    raise OpError(index=index, op=op, reason=KEY_NOT_FOUND, key=key)
                blocks.pop(pos)
                rebuild_positions()
            case SetContent(key=key, content=content):
                pos = positions.get(key)
                if key == HEAD or pos is None:
                    raise OpError(index=index, op=op, reason=KEY_NOT_FOUND, key=key)
                blocks[pos] = replace(blocks[pos], content=content)
            case SetAttrs(key=key, attrs=attrs):
                pos = positions.get(key)
                if key == HEAD or pos is None:
                    raise OpError(index=index, op=op, reason=KEY_NOT_FOUND, key=key)
                blocks[pos] = replace(blocks[pos], attrs=dict(attrs))
            case _:
                raise TypeError(f"not an Op: {op!r}")

    new = DocumentSnapshot(
        id="",
        blocks=tuple(blocks),
        doc_attrs=snapshot.doc_attrs,
        key_cursor=cursor,
    )
    return replace(new, id=snapshot_id(new))
