"""surface：Agent 操作面——patch 方言、降解与 run_patch。

公开接口见下文 __all__；设计规格见 Docs/Design/07-agent-api.md，
core op 语义见 04-ir-ops.md。

链路：patch 文本 --parse--> SurfaceOp 序列 --degrade--> core op 序列
--apply--> 新快照 --渲染--> PatchResult。
"""

from surface.degrade import CoreOpEntry, Origin, degrade
from surface.errors import PATTERN_NOT_FOUND, ParseError, SurfaceError, op_to_dict
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
from surface.parse import parse
from surface.patch import (
    STATUS_APPENDED,
    STATUS_MERGED,
    STATUS_MOVED,
    STATUS_REMOVED,
    STATUS_UPDATED,
    AffectedBlock,
    PatchResult,
    run_patch,
)

__all__ = [
    # SurfaceOp 标准集
    "SurfaceOp",
    "SetContent",
    "SetAttrs",
    "Append",
    "Remove",
    "Move",
    "Merge",
    "Replace",
    "LineSpan",
    "HEAD_ID",
    # 方言 fn
    "parse",
    "ParseError",
    # 降解
    "degrade",
    "CoreOpEntry",
    "Origin",
    "SurfaceError",
    "op_to_dict",
    "PATTERN_NOT_FOUND",
    # run_patch 与回执
    "run_patch",
    "PatchResult",
    "AffectedBlock",
    "STATUS_APPENDED",
    "STATUS_UPDATED",
    "STATUS_MOVED",
    "STATUS_MERGED",
    "STATUS_REMOVED",
]
