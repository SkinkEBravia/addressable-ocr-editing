"""agent：Session 契约、上下文组装、agent loop、标准工具配置。

设计规格见 Docs/Design/09-tools.md。
"""

from agent.assembly import build_initial_messages, format_input
from agent.config import (
    REGISTRY,
    ToolsetConfig,
    build_toolset,
    load_toolset_config,
    toolset_config_from_dict,
)
from agent.loop import run_session, start_session
from agent.session import TAPE_VERSION, Session, Turn
from agent.toolset import (
    DONE,
    Budget,
    Done,
    ToolCall,
    ToolParseError,
    ToolResult,
    ToolSet,
)

__all__ = [
    "Session",
    "Turn",
    "TAPE_VERSION",
    "ToolSet",
    "ToolCall",
    "ToolResult",
    "ToolParseError",
    "Done",
    "DONE",
    "Budget",
    "build_initial_messages",
    "format_input",
    "start_session",
    "run_session",
    "ToolsetConfig",
    "load_toolset_config",
    "toolset_config_from_dict",
    "build_toolset",
    "REGISTRY",
]
