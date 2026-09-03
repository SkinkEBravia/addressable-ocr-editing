"""view：快照的消费方之一（DocumentSnapshot -> View）。

公开接口见下文 __all__；设计规格见 Docs/Design/06-view.md，
默认组件（blockkey-as-is / xml-ish）见 Docs/Design/07-agent-api.md。
"""

from view.defaults import blockkey_as_is, cat_n, line_number, xml_ish
from view.present import present, render_blocks
from view.types import (
    AgentBlockId,
    AgentIdStrategy,
    AgentView,
    Annotator,
    ReferenceMap,
    View,
    ViewError,
    ViewId,
)

__all__ = [
    "AgentBlockId",
    "ViewId",
    "AgentIdStrategy",
    "Annotator",
    "ViewError",
    "View",
    "AgentView",
    "ReferenceMap",
    "present",
    "render_blocks",
    "blockkey_as_is",
    "xml_ish",
    "line_number",
    "cat_n",
]
