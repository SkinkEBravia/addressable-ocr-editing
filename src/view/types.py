"""view 的数据类型：View / AgentView / ReferenceMap / ViewError 与策略签名。

对应 Docs/Design/06-view.md「定义」节。

View 是从快照导出的对象，服务于特定目的；AgentView 是其中服务 Agent
的一种（payload 为插入 ID 标注的还原文本），用子类表示并把 payload 收窄
为 str，同时携带随 View 一起产出的 ReferenceMap。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ir import Attrs, Block, BlockKey, JsonValue, SnapshotId

__all__ = [
    "AgentBlockId",
    "ViewId",
    "AgentIdStrategy",
    "Annotator",
    "ViewError",
    "View",
    "AgentView",
    "ReferenceMap",
]

type AgentBlockId = str
"""Agent 看到的块 ID。由 AgentIdStrategy 生成，同一快照内必须互不相同。"""

type ViewId = str
"""View 的身份，由 Presenter 分配。"""

type AgentIdStrategy = Callable[[Block, int], AgentBlockId]
"""id 策略：(block, index) -> AgentBlockId。允许读取 block.attrs。"""

type Annotator = Callable[[AgentBlockId, str], str]
"""标注形式：(agent_id, content) -> 带 ID 标注的文本。与 id 策略相互独立。"""


class ViewError(Exception):
    """View 导出失败：策略产出重复 id、ReferenceMap 非双射等。"""


@dataclass(frozen=True)
class ReferenceMap:
    """``AgentBlockId <-> BlockKey`` 的双射，随 AgentView 一起产出。

    覆盖来源快照的全部 blocks；patch 降解时经它把 AgentBlockId 换回
    BlockKey。构造时校验双射，违反时抛 ViewError。
    """

    forward: dict[AgentBlockId, BlockKey]
    """AgentBlockId -> BlockKey。"""

    _reverse: dict[BlockKey, AgentBlockId] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        counts = len(self.forward)
        if len(set(self.forward.values())) != counts:
            raise ViewError("reference map is not bijective: duplicate block keys")
        object.__setattr__(self, "_reverse", {v: k for k, v in self.forward.items()})

    def key_of(self, agent_id: AgentBlockId) -> BlockKey:
        """AgentBlockId -> BlockKey。未知 id 抛 KeyError。"""
        return self.forward[agent_id]

    def agent_id_of(self, key: BlockKey) -> AgentBlockId:
        """BlockKey -> AgentBlockId。未知 key 抛 KeyError。"""
        return self._reverse[key]

    def __getitem__(self, agent_id: AgentBlockId) -> BlockKey:
        return self.key_of(agent_id)

    def __contains__(self, agent_id: object) -> bool:
        return agent_id in self.forward

    def __len__(self) -> int:
        return len(self.forward)

    def items(self) -> tuple[tuple[AgentBlockId, BlockKey], ...]:
        return tuple(self.forward.items())

    def as_dict(self) -> dict[AgentBlockId, BlockKey]:
        """正向映射的副本；修改副本不影响本对象。"""
        return dict(self.forward)


@dataclass(frozen=True)
class View:
    """数据接口。从快照导出的对象，服务于特定目的。"""

    view_id: ViewId
    """View 的身份，由 Presenter 分配。"""

    snapshot_id: SnapshotId
    """来源快照。"""

    payload: JsonValue
    """展示内容。"""

    render_spec: Attrs
    """导出元数据（策略名、标注形式名、kind 等）。"""


@dataclass(frozen=True)
class AgentView(View):
    """View 的一种，服务 Agent。

    payload 为插入了 ID 标注的还原文本（str）；分块方式与快照一致，
    但使用另一套 ID——AgentBlockId。reference_map 随 View 一起产出，
    覆盖快照的全部 blocks。
    """

    payload: str
    reference_map: ReferenceMap
