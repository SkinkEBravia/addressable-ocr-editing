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
    Replace,
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
    errors: tuple["SurfaceError", ...] = ()
    """best_effort 模式下被跳过 op 的失败清单；atomic 模式恒为空（失败即抛）。"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "affected": [ab.to_dict() for ab in self.affected],
            "errors": [e.to_dict() for e in self.errors],
        }


APPLY_ATOMIC = "atomic"
"""默认应用策略：整批原子，任一失败全批回滚（store 不变）。"""

APPLY_BEST_EFFORT = "best_effort"
"""逐条应用策略：op 按文本顺序逐条 degrade+apply+save，失败的跳过并记入
``PatchResult.errors``，其余照常生效（假设：OCR 修复的 op 互不影响——
链式叠加对成功 op 仍按文本顺序成立）。语法错误（ParseError）仍整批拒绝。"""


def run_patch(
    store: Store,
    patch_text: str,
    strategy: AgentIdStrategy,
    annotator: Annotator,
    *,
    mode: str = APPLY_ATOMIC,
) -> PatchResult:
    """load(current) -> parse -> degrade -> apply -> save -> 渲染受影响块。

    ``mode=atomic``（默认）：失败抛 ``ParseError``（解析）或
    ``SurfaceError``（降解 / apply）；失败时 store 不变。
    ``mode=best_effort``：语义失败逐条跳过、记入回执 ``errors``，
    其余照常提交；只有 ParseError（语法）仍抛出。
    """
    snapshot = ir.load(store, ir.current(store))
    surface_ops = parse(patch_text)
    ref_map = present(snapshot, strategy, annotator).reference_map
    if mode == APPLY_ATOMIC:
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
    if mode == APPLY_BEST_EFFORT:
        return _run_best_effort(
            store, snapshot, surface_ops, ref_map, strategy, annotator
        )
    raise ValueError(f"unknown apply mode: {mode!r}")


def _run_best_effort(
    store: Store,
    snapshot: DocumentSnapshot,
    surface_ops: tuple[SurfaceOp, ...],
    ref_map: ReferenceMap,
    strategy: AgentIdStrategy,
    annotator: Annotator,
) -> PatchResult:
    """逐条应用：id 一律按 patch 前的 View 解析（07 规则），内容读取看
    当前状态（成功 op 间链式叠加保持）。失败的 op 跳过，store 停在前一个
    成功状态。"""
    import dataclasses

    old = snapshot
    current = snapshot
    errors: list[SurfaceError] = []
    applied: list[SurfaceOp] = []
    for i, sop in enumerate(surface_ops):
        try:
            entries = degrade((sop,), ref_map, current)
            new_snapshot = ir.apply(current, tuple(op for op, _ in entries))
        except SurfaceError as exc:  # 降解失败（未知 id / PATTERN_NOT_FOUND）
            errors.append(dataclasses.replace(exc, surface_index=i))
            continue
        except OpError as exc:  # apply 失败
            errors.append(
                dataclasses.replace(_wrap_op_error(exc, entries), surface_index=i)
            )
            continue
        ir.save(store, new_snapshot)
        current = new_snapshot
        applied.append(sop)
    affected = _affected(
        old=old,
        new=current,
        surface_ops=tuple(applied),
        old_ref_map=ref_map,
        strategy=strategy,
        annotator=annotator,
    )
    return PatchResult(
        snapshot_id=current.id, affected=affected, errors=tuple(errors)
    )


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
            case SetContent(id=agent_id) | SetAttrs(id=agent_id) | Replace(id=agent_id):
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
    # 同一块可能被多条内容 op 命中（如连续 replace）：回执中每块只出现一次，
    # 位置取首次出现，status 取最后一次
    order: list[BlockKey] = []
    final_status: dict[BlockKey, str] = {}
    for status, key in plan:
        if key not in final_status:
            order.append(key)
        final_status[key] = status
    present_entries: list[tuple[int, AffectedBlock]] = []
    removed_entries: list[tuple[int, AffectedBlock]] = []
    for key in order:
        status = final_status[key]
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
