"""toolsets：工具配置与多轮 loop（Docs/Design/09-tools.md）。

标准工具配置注册表；``build_toolset`` 由 TOML 配置装配（见 experiment.config）。
"""

from toolsets.basic import NoopToolSet, RewriteToolSet
from toolsets.core import (
    DONE,
    Budget,
    Done,
    LoopResult,
    Tool,
    ToolCall,
    ToolContext,
    ToolParseError,
    ToolResult,
    ToolSet,
    TurnRecord,
    run_loop,
    run_toolset,
)
from toolsets.find_replace import FindReplaceToolSet
from toolsets.patch import PatchToolSet
from toolsets.rewrite_pieces import RewritePiecesToolSet

REGISTRY = {
    "noop": NoopToolSet,
    "rewrite": RewriteToolSet,
    "patch": PatchToolSet,
    "rewrite_pieces": RewritePiecesToolSet,
    "find_replace": FindReplaceToolSet,
}
"""包内标准工具集名 -> 类。"""

__all__ = [
    "NoopToolSet",
    "RewriteToolSet",
    "PatchToolSet",
    "RewritePiecesToolSet",
    "FindReplaceToolSet",
    "REGISTRY",
    "ToolCall",
    "ToolResult",
    "Tool",
    "Done",
    "DONE",
    "ToolParseError",
    "ToolContext",
    "ToolSet",
    "Budget",
    "TurnRecord",
    "LoopResult",
    "run_loop",
    "run_toolset",
]
