"""Presenter：DocumentSnapshot -> AgentView。

对应 Docs/Design/06-view.md「呈现接口」节。Presenter 消费快照，
不改动快照、不执行文件读写；视图身份由最终视图数据的内容哈希确定。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from hashlib import sha256

from ir import Block, DocumentSnapshot, canonical_json

from view.types import (
    AgentBlockId,
    AgentIdStrategy,
    AgentView,
    Annotator,
    ReferenceMap,
    ViewError,
    View,
)

__all__ = ["present", "render_blocks", "present_file", "file_header"]


def _view_id(view: View) -> str:
    data = {
        "snapshot_id": view.snapshot_id,
        "payload": view.payload,
        "render_spec": view.render_spec,
    }
    if isinstance(view, AgentView):
        data["reference_map"] = view.reference_map.as_dict()
    return "v-" + sha256(canonical_json(data).encode("utf-8")).hexdigest()[:16]


def file_header(label: str, filename: str) -> str:
    """路径抬头：``--- [{label}: {filename}] ---\\n``。单处定义，供工具集复用。"""
    return f"--- [{label}: {filename}] ---\n"


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
    """DocumentSnapshot -> AgentView（只读快照，不执行文件读写）。

    - payload = 按序对每个块应用 ``annotator(strategy(block, i), block.content)``
      并拼接；空快照对应空串。
    - reference_map 覆盖快照的全部 blocks，双射（重复 id 抛 ViewError）。
    - view_id 按最终展示、来源、元数据和地址映射计算，同一输入得到相同身份。
    - render_spec 记录 kind 与 strategy / annotator 的名称。
    """
    payload, reference_map = render_blocks(snapshot.blocks, strategy, annotator)
    view = AgentView(
        view_id="",
        snapshot_id=snapshot.id,
        payload=payload,
        render_spec={
            "kind": "agent",
            "strategy": _component_name(strategy),
            "annotator": _component_name(annotator),
        },
        reference_map=reference_map,
    )
    return replace(view, view_id=_view_id(view))


def present_file(
    snapshot: DocumentSnapshot,
    filename: str,
    prefix: str | None = None,
    annotator: Annotator | None = None,
    strategy: AgentIdStrategy | None = None,
    label: str = "File",
) -> AgentView:
    """带有文件标识抬头与前缀命名空间 ID 的专用 Presenter。

    payload = file_header(label, filename) + 块展示（允许无标注）

    - strategy 缺省时沿用原行为：给定 ``prefix`` 走 ``prefixed_blockkey``，
      否则 ``blockkey_as_is``；显式给 ``strategy`` 时优先（``prefix`` 不再生效）。
    - ``label`` 只改抬头用词（默认 ``File``），供非文件语义的处理对象使用。
    """
    from view.defaults import blockkey_as_is, prefixed_blockkey, xml_ish

    actual_annotator = annotator if annotator is not None else xml_ish
    if strategy is None:
        strategy = prefixed_blockkey(prefix) if prefix else blockkey_as_is
    base_view = present(snapshot, strategy, actual_annotator)
    header = file_header(label, filename)
    view = AgentView(
        view_id="",
        snapshot_id=base_view.snapshot_id,
        payload=header + base_view.payload,
        render_spec={
            **base_view.render_spec,
            "filename": filename,
            "prefix": prefix,
            "label": label,
        },
        reference_map=base_view.reference_map,
    )
    return replace(view, view_id=_view_id(view))
