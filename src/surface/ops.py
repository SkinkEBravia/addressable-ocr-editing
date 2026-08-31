"""surface 操作集：七个 SurfaceOp（tagged union）。

对应 Docs/Design/07-agent-api.md「SurfaceOp 标准集」节。

四个核心 op 的直译（SetContent / SetAttrs / Append / Remove）+ 三个包装
（Move / Merge / Replace）。每条 op 记录其在 patch 文本中的位置（行号区间），
供报错定位。id / anchor 均为 AgentBlockId；``HEAD_ID`` 是 agent 侧的
保留锚点（文档头部），仅在 anchor 位置合法。
"""

from __future__ import annotations

from dataclasses import dataclass

from ir import Attrs
from view.types import AgentBlockId

__all__ = [
    "LineSpan",
    "HEAD_ID",
    "SurfaceOp",
    "SetContent",
    "SetAttrs",
    "Append",
    "Remove",
    "Move",
    "Merge",
    "Replace",
]

type LineSpan = tuple[int, int]
"""patch 文本中的行号区间 ``(start, end)``，1 起、含两端。一行一个调用时 start == end。"""

HEAD_ID = "HEAD"
"""agent 侧保留锚点 id：文档头部（降解为 ``ir.HEAD``，不经 ReferenceMap）。"""


class SurfaceOp:
    """surface 操作的基类（tagged union 的 tag）。"""

    __slots__ = ()
    position: LineSpan


@dataclass(frozen=True)
class SetContent(SurfaceOp):
    """``set_content(id, text)``：整体替换内容 -> ``ir.SetContent(key, text)``。"""

    position: LineSpan
    id: AgentBlockId
    text: str


@dataclass(frozen=True)
class SetAttrs(SurfaceOp):
    """``set_attrs(id, obj)``：整体替换 attrs -> ``ir.SetAttrs(key, obj)``。"""

    position: LineSpan
    id: AgentBlockId
    attrs: Attrs


@dataclass(frozen=True)
class Append(SurfaceOp):
    """``append(anchor, text, attrs?)``：插入到 anchor 之后 -> ``ir.Append(draft, at: key)``。

    anchor 可取保留值 ``HEAD_ID``（文首）。
    """

    position: LineSpan
    anchor: AgentBlockId
    text: str
    attrs: Attrs | None = None


@dataclass(frozen=True)
class Remove(SurfaceOp):
    """``remove(id)``：移除块 -> ``ir.Remove(key)``。"""

    position: LineSpan
    id: AgentBlockId


@dataclass(frozen=True)
class Move(SurfaceOp):
    """``move(id, anchor)``：移动到 anchor 之后。

    包装：``Remove(key) + Append(draft_of(key), at: anchor)``——身份变更新 key。
    """

    position: LineSpan
    id: AgentBlockId
    anchor: AgentBlockId


@dataclass(frozen=True)
class Merge(SurfaceOp):
    """``merge(a, b)``：b 并入 a 末尾，b 移除。

    包装：``SetContent(a, a.content + b.content) + Remove(b)``。
    """

    position: LineSpan
    a: AgentBlockId
    b: AgentBlockId


@dataclass(frozen=True)
class Replace(SurfaceOp):
    """``replace(id, old, new)``：块内片段替换，``old`` 的全部出现处换成 ``new``。

    包装：``SetContent(key, content.replace(old, new))``。``old`` 必须在块
    内容中至少出现一次，否则降解失败（``PATTERN_NOT_FOUND``）。定位由块
    负责（行级），变更粒度到片段——稀疏错误下避免整块重写。
    """

    position: LineSpan
    id: AgentBlockId
    old: str
    new: str
