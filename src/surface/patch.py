"""run_patch：一次 patch 的完整链路与回执（PatchResult）。

对应 Docs/Design/07-agent-api.md「接口」节：

    load(current) -> parse -> degrade -> apply -> save -> 渲染受影响块 -> PatchResult

行为规则：

- core ops 一次性 ``apply``（apply 本身原子），全部成功后才 ``save``——
  patch 失败时 store 不变。
- ``apply`` 失败时用 ``OpError.index`` 查 origin 回溯，包装成
  ``SurfaceError``（stage="apply"）抛出；解析失败抛 ``ParseError``，
  降解失败抛 ``SurfaceError``（stage="degrade"）。
- 受影响块用同一 ``(strategy, annotator)`` 渲染；``removed`` 时
  ``annotated=None``。
- ``affected`` 按新文档序排列；被移除的块在新文档中没有位置，按其在旧
  文档中的顺序排在最后（本实现选择的约定）。

与 07 文档签名的一处差异：失败不返回 ``{"error": ...}`` 而是抛
``ParseError`` / ``SurfaceError``——两者都带 ``to_dict()``，CLI 凭
异常类型映射退出码（1 / 2 / 3）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import ir
from ir import BlockKey, DocumentSnapshot, OpError, SnapshotId, Store
from view import (
    AgentBlockId,
    AgentIdStrategy,
    Annotator,
    ReferenceMap,
    present,
)

from surface.degrade import CoreOpEntry, degrade
from surface.errors import STAGE_APPLY, SurfaceError
from surface.ops import (
    Append,
    Merge,
    Move,
    Remove,
    SetAttrs,
    SetContent,
    SurfaceOp,
)
from surface.parse import parse

__all__ = [
    "AffectedBlock",
    "PatchResult",
    "STATUS_APPENDED",
    "STATUS_UPDATED",
    "STATUS_MOVED",
    "STATUS_MERGED",
    "STATUS_REMOVED",
    "run_patch",
]

STATUS_APPENDED = "appended"
STATUS_UPDATED = "updated"
STATUS_MOVED = "moved"
STATUS_MERGED = "merged"
STATUS_REMOVED = "removed"


@dataclass(frozen=True)
class AffectedBlock:
    """一个受影响的块：改完即可核对，不必重新拉全量 View。"""

    key: BlockKey
    agent_id: AgentBlockId
    """新 View 下的 id（removed 时为旧 View 下的 id）。"""
    status: str
    """appended / updated / moved / merged / removed。"""
    annotated: str | None
    """用同一 (strategy, annotator) 渲染的带标注内容；removed 时为 None。"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "agent_id": self.agent_id,
            "status": self.status,
            "annotated": self.annotated,
        }


@dataclass(frozen=True)
class PatchResult:
    """数据接口。一次 patch 的回执。"""

    snapshot_id: SnapshotId
    affected: tuple[AffectedBlock, ...]
    """受影响的块，按（新）文档序；removed 的块排在最后。"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "affected": [ab.to_dict() for ab in self.affected],
        }


def run_patch(
    store: Store,
    patch_text: str,
    strategy: AgentIdStrategy,
    annotator: Annotator,
) -> PatchResult:
    """load(current) -> parse -> degrade -> apply -> save -> 渲染受影响块。

    失败抛 ``ParseError``（解析）或 ``SurfaceError``（降解 / apply）；
    失败时 store 不变（save 只在全部 core op 成功应用之后执行）。
    """
    snapshot = ir.load(store, ir.current(store))
    surface_ops = parse(patch_text)
    ref_map = present(snapshot, strategy, annotator).reference_map
    entries = degrade(surface_ops, ref_map, snapshot)
    core_ops = tuple(op for op, _ in entries)
    try:
        new_snapshot = ir.apply(snapshot, core_ops)
    except OpError as exc:
        raise _wrap_op_error(exc, entries) from exc
    ir.save(store, new_snapshot)
    affected = _affected(
        old=snapshot,
        new=new_snapshot,
        surface_ops=surface_ops,
        old_ref_map=ref_map,
        strategy=strategy,
        annotator=annotator,
    )
    return PatchResult(snapshot_id=new_snapshot.id, affected=affected)


def _wrap_op_error(exc: OpError, entries: tuple[CoreOpEntry, ...]) -> SurfaceError:
    """用 OpError.index 查 origin 回溯到 SurfaceOp，包装成 SurfaceError。"""
    origin = entries[exc.index][1]
    expanded = tuple(
        op for op, o in entries if o.surface_index == origin.surface_index
    )
    return SurfaceError(
        stage=STAGE_APPLY,
        surface_index=origin.surface_index,
        position=origin.position,
        expanded=expanded,
        cause=exc.reason,
        message=str(exc),
    )


def _plan(
    surface_ops: tuple[SurfaceOp, ...],
    old_ref_map: ReferenceMap,
    key_cursor: int,
) -> list[tuple[str, BlockKey]]:
    """按 surface op 顺序推导 (status, key) 计划。

    新 key 由 apply 前的 ``snapshot.key_cursor`` 推导：批次内第 n 个
    ir.Append（按序，move 贡献一个）取 key ``b{cursor + n}``。
    """
    plan: list[tuple[str, BlockKey]] = []
    cursor = key_cursor
    for sop in surface_ops:
        match sop:
            case SetContent(id=agent_id) | SetAttrs(id=agent_id):
                plan.append((STATUS_UPDATED, old_ref_map.key_of(agent_id)))
            case Append():
                plan.append((STATUS_APPENDED, f"b{cursor}"))
                cursor += 1
            case Remove(id=agent_id):
                plan.append((STATUS_REMOVED, old_ref_map.key_of(agent_id)))
            case Move(id=agent_id):
                plan.append((STATUS_MOVED, f"b{cursor}"))
                cursor += 1
            case Merge(a=a_id, b=b_id):
                plan.append((STATUS_MERGED, old_ref_map.key_of(a_id)))
                plan.append((STATUS_REMOVED, old_ref_map.key_of(b_id)))
            case _:
                raise TypeError(f"not a SurfaceOp: {sop!r}")
    return plan


def _affected(
    old: DocumentSnapshot,
    new: DocumentSnapshot,
    surface_ops: tuple[SurfaceOp, ...],
    old_ref_map: ReferenceMap,
    strategy: AgentIdStrategy,
    annotator: Annotator,
) -> tuple[AffectedBlock, ...]:
    """渲染受影响块。

    agent_id 用 strategy 对新快照中的块重新计算（对新快照做一次全量
    present，保证与下一次全量 View 一致）；removed 的块取旧 View 下的 id。
    """
    new_view = present(new, strategy, annotator)
    new_by_key = {b.key: b for b in new.blocks}
    new_index = {b.key: i for i, b in enumerate(new.blocks)}
    old_index = {b.key: i for i, b in enumerate(old.blocks)}

    plan = _plan(surface_ops, old_ref_map, old.key_cursor)
    present_entries: list[tuple[int, AffectedBlock]] = []
    removed_entries: list[tuple[int, AffectedBlock]] = []
    for status, key in plan:
        if status == STATUS_REMOVED:
            removed_entries.append(
                (
                    old_index[key],
                    AffectedBlock(
                        key=key,
                        agent_id=old_ref_map.agent_id_of(key),
                        status=status,
                        annotated=None,
                    ),
                )
            )
        else:
            block = new_by_key[key]
            agent_id = new_view.reference_map.agent_id_of(key)
            present_entries.append(
                (
                    new_index[key],
                    AffectedBlock(
                        key=key,
                        agent_id=agent_id,
                        status=status,
                        annotated=annotator(agent_id, block.content),
                    ),
                )
            )
    present_entries.sort(key=lambda t: t[0])
    removed_entries.sort(key=lambda t: t[0])
    return tuple(ab for _, ab in present_entries + removed_entries)
