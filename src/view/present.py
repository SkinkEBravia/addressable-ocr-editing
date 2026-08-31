"""Presenter：DocumentSnapshot -> AgentView。

对应 Docs/Design/06-view.md「接口」节。Presenter 是统一输出接口的消费方：
纯函数、无副作用、不改动快照。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from uuid import uuid4

from ir import Block, DocumentSnapshot

from view.types import (
    AgentBlockId,
    AgentIdStrategy,
    AgentView,
    Annotator,
    ReferenceMap,
    ViewError,
)

__all__ = ["present", "render_blocks"]


def _component_name(component: Callable[..., object]) -> str:
    """组件名：优先 __name__，回退类型名（可调用对象）。"""
    name = getattr(component, "__name__", None)
    return name if isinstance(name, str) else type(component).__name__


def render_blocks(
    blocks: Sequence[Block],
    strategy: AgentIdStrategy,
    annotator: Annotator,
) -> tuple[str, ReferenceMap]:
    """渲染给定块序列：(payload, ReferenceMap)。

    供 patch 后渲染受影响块等子集渲染使用。payload = 按序对每个块应用
    ``annotator(strategy(block, i), block.content)`` 并拼接；``i`` 是该块
    在本序列中的序号，因此对下标无关的策略（如默认 blockkey-as-is），
    子集渲染结果与全量 View 中的对应片段逐字符一致。

    策略产出重复 id 时抛 ViewError（双射不成立）。
    """
    forward: dict[AgentBlockId, str] = {}
    parts: list[str] = []
    for index, block in enumerate(blocks):
        agent_id = strategy(block, index)
        if agent_id in forward:
            raise ViewError(
                f"strategy produced duplicate agent id {agent_id!r} "
                f"(blocks {forward[agent_id]!r} and {block.key!r})"
            )
        forward[agent_id] = block.key
        parts.append(annotator(agent_id, block.content))
    return "".join(parts), ReferenceMap(forward)


def present(
    snapshot: DocumentSnapshot,
    strategy: AgentIdStrategy,
    annotator: Annotator,
) -> AgentView:
    """DocumentSnapshot -> AgentView（纯函数，无副作用，不改动快照）。

    - payload = 按序对每个块应用 ``annotator(strategy(block, i), block.content)``
      并拼接；空快照对应空串。
    - reference_map 覆盖快照的全部 blocks，双射（重复 id 抛 ViewError）。
    - view_id 由 Presenter 分配（uuid4 hex）；同一
      (snapshot, strategy, annotator) 的 payload 与 ReferenceMap 确定。
    - render_spec 记录 kind 与 strategy / annotator 的名称。
    """
    payload, reference_map = render_blocks(snapshot.blocks, strategy, annotator)
    return AgentView(
        view_id=uuid4().hex,
        snapshot_id=snapshot.id,
        payload=payload,
        render_spec={
            "kind": "agent",
            "strategy": _component_name(strategy),
            "annotator": _component_name(annotator),
        },
        reference_map=reference_map,
    )
