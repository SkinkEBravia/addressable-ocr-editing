"""降解：SurfaceOp 序列 -> core op 序列（带溯源信息）。

对应 Docs/Design/07-agent-api.md「降解」节与 04-ir-ops.md「surface 语义的
降解」节：

- ``AgentBlockId`` 经 ``ReferenceMap`` 换回 ``BlockKey``；``HEAD`` 直接映射
  为 ``ir.HEAD``（不经 ref_map，且仅在 anchor 位置合法）。
- 包装语义展开：``move = Remove + Append``（新身份）；``merge =
  SetContent(a.content + b.content) + Remove(b)``；``replace =
  SetContent(k, content.replace(old, new))``（``old`` 未出现则降解失败，
  原因码 ``PATTERN_NOT_FOUND``）。
- ``CoreOpEntry = (Op, Origin)``；``Origin`` 指回产生它的 SurfaceOp
  （序号 + 文本位置），是报错包装的前提。
- 未知 ``AgentBlockId`` 等直接产出 ``SurfaceError``（stage="degrade"），
  不进入 apply。

与 07 文档签名的一处补充：降解需要读取 patch 前快照的块内容（move 的
draft、merge 的 a.content + b.content、replace 的 content），因此签名带
第三个参数 ``snapshot``。move / merge / replace 读取的都是 **patch 之前**
快照的内容——降解是静态展开，不感知同批次内前面的 set_content 等修改。
"""

from __future__ import annotations

from dataclasses import dataclass

import ir
from ir import Block, DocumentSnapshot, Op
from view import ReferenceMap

from surface.errors import PATTERN_NOT_FOUND, STAGE_DEGRADE, SurfaceError
from surface.ops import (
    HEAD_ID,
    Append,
    LineSpan,
    Merge,
    Move,
    Remove,
    Replace,
    SetAttrs,
    SetContent,
    SurfaceOp,
)

__all__ = ["Origin", "CoreOpEntry", "degrade"]


@dataclass(frozen=True)
class Origin:
    """一条 core op 的溯源信息：产生它的 SurfaceOp 的序号与文本位置。"""

    surface_index: int
    """SurfaceOp 在 patch 中的序号（0 起）。"""
    position: LineSpan
    """SurfaceOp 在 patch 文本中的行号区间。"""


type CoreOpEntry = tuple[Op, Origin]
"""(core op, origin)。origin 指回产生它的 SurfaceOp（序号 + 文本位置）。"""


def _unknown_id(agent_id: str, index: int, position: LineSpan) -> SurfaceError:
    return SurfaceError(
        stage=STAGE_DEGRADE,
        surface_index=index,
        position=position,
        expanded=(),
        cause=None,
        message=(
            f"unknown agent block id {agent_id!r}: not in the reference map "
            "of the pre-patch view (stale view? re-render before patching)"
        ),
    )


def _target_key(agent_id: str, ref_map: ReferenceMap, index: int, position: LineSpan) -> str:
    """目标 id（set_content / set_attrs / remove / move / merge 的块）-> BlockKey。"""
    if agent_id == HEAD_ID:
        raise SurfaceError(
            stage=STAGE_DEGRADE,
            surface_index=index,
            position=position,
            expanded=(),
            cause=None,
            message=f"{HEAD_ID} is a reserved anchor and cannot be used as a target id",
        )
    try:
        return ref_map.key_of(agent_id)
    except KeyError:
        raise _unknown_id(agent_id, index, position) from None


def _anchor_key(agent_id: str, ref_map: ReferenceMap, index: int, position: LineSpan) -> str:
    """锚点 id（append / move 的 anchor）-> BlockKey；HEAD 直接映射 ir.HEAD。"""
    if agent_id == HEAD_ID:
        return ir.HEAD
    try:
        return ref_map.key_of(agent_id)
    except KeyError:
        raise _unknown_id(agent_id, index, position) from None


def _block(
    by_key: dict[str, Block], key: str, index: int, position: LineSpan
) -> Block:
    """从 patch 前快照取块（move / merge 的展开需要其 content / attrs）。"""
    block = by_key.get(key)
    if block is None:
        raise SurfaceError(
            stage=STAGE_DEGRADE,
            surface_index=index,
            position=position,
            expanded=(),
            cause=None,
            message=f"block {key!r} not found in the pre-patch snapshot",
        )
    return block


def degrade(
    surface_ops: tuple[SurfaceOp, ...],
    ref_map: ReferenceMap,
    snapshot: DocumentSnapshot,
) -> tuple[CoreOpEntry, ...]:
    """SurfaceOp 序列 -> core op 序列（按文本顺序，供一次性 apply）。

    - ``ref_map`` 必须属于 patch 之前的 View（同一 patch 内不得引用本次
      新建的块）。
    - ``snapshot`` 为 patch 前快照，供 move / merge 读取块内容。
    - 未知 AgentBlockId 等降解失败抛 ``SurfaceError``（stage="degrade"）。
    """
    by_key = {b.key: b for b in snapshot.blocks}
    entries: list[CoreOpEntry] = []
    for index, sop in enumerate(surface_ops):
        position = sop.position
        match sop:
            case SetContent(id=agent_id, text=text):
                key = _target_key(agent_id, ref_map, index, position)
                core = [ir.SetContent(key=key, content=text)]
            case SetAttrs(id=agent_id, attrs=attrs):
                key = _target_key(agent_id, ref_map, index, position)
                core = [ir.SetAttrs(key=key, attrs=dict(attrs))]
            case Append(anchor=anchor, text=text, attrs=attrs):
                at = _anchor_key(anchor, ref_map, index, position)
                core = [
                    ir.Append(
                        draft_content=text,
                        draft_attrs=dict(attrs) if attrs else {},
                        at=at,
                    )
                ]
            case Remove(id=agent_id):
                key = _target_key(agent_id, ref_map, index, position)
                core = [ir.Remove(key=key)]
            case Move(id=agent_id, anchor=anchor):
                key = _target_key(agent_id, ref_map, index, position)
                at = _anchor_key(anchor, ref_map, index, position)
                block = _block(by_key, key, index, position)
                core = [
                    ir.Remove(key=key),
                    ir.Append(
                        draft_content=block.content,
                        draft_attrs=dict(block.attrs),
                        at=at,
                    ),
                ]
            case Merge(a=a_id, b=b_id):
                key_a = _target_key(a_id, ref_map, index, position)
                key_b = _target_key(b_id, ref_map, index, position)
                block_a = _block(by_key, key_a, index, position)
                block_b = _block(by_key, key_b, index, position)
                core = [
                    ir.SetContent(key=key_a, content=block_a.content + block_b.content),
                    ir.Remove(key=key_b),
                ]
            case Replace(id=agent_id, old=old, new=new):
                key = _target_key(agent_id, ref_map, index, position)
                block = _block(by_key, key, index, position)
                if old not in block.content:
                    raise SurfaceError(
                        stage=STAGE_DEGRADE,
                        surface_index=index,
                        position=position,
                        expanded=(),
                        cause=PATTERN_NOT_FOUND,
                        message=(
                            f"replace: pattern {old!r} not found in block "
                            f"{agent_id!r} (stale view? re-render before patching)"
                        ),
                    )
                core = [ir.SetContent(key=key, content=block.content.replace(old, new))]
            case _:
                raise TypeError(f"not a SurfaceOp: {sop!r}")
        entries.extend(
            (op, Origin(surface_index=index, position=position)) for op in core
        )
    return tuple(entries)
