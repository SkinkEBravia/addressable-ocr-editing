"""surface 层的错误类型：ParseError 与 SurfaceError。

对应 Docs/Design/07-agent-api.md「错误回传」节：

    OpError(index, op, reason)          # IR 层
      └─ origin ──> SurfaceError        # 操作面层（本模块）
           └─ 方言格式化 ──> 报错输出    # 文本层（CLI）

两类错误都可 ``to_dict()``，供 CLI 的 ``-f json`` 输出。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ir import Append, Op, Remove, SetAttrs, SetContent

from surface.ops import LineSpan

__all__ = ["ParseError", "SurfaceError", "op_to_dict", "PATTERN_NOT_FOUND"]

STAGE_DEGRADE = "degrade"
"""降解阶段失败（未知 AgentBlockId 等）：不进入 apply。"""

STAGE_APPLY = "apply"
"""apply 阶段失败：用 OpError.index 查 origin 回溯到 SurfaceOp。"""

PATTERN_NOT_FOUND = "PATTERN_NOT_FOUND"
"""replace 的 ``old`` 在块内容中未出现（降解失败的原因码，机器可判读）。"""


class ParseError(Exception):
    """patch 方言解析失败。携带行号（1 起）与原因。"""

    def __init__(self, line: int, reason: str) -> None:
        super().__init__(f"line {line}: {reason}")
        self.line = line
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {"error": "parse", "line": self.line, "reason": self.reason}


def op_to_dict(op: Op) -> dict[str, Any]:
    """core op -> JSON 可序列化字典（SurfaceError.expanded 的序列化形式）。"""
    match op:
        case Append(draft_content=content, draft_attrs=attrs, at=anchor):
            return {"op": "append", "at": anchor, "content": content, "attrs": attrs}
        case Remove(key=key):
            return {"op": "remove", "key": key}
        case SetContent(key=key, content=content):
            return {"op": "set_content", "key": key, "content": content}
        case SetAttrs(key=key, attrs=attrs):
            return {"op": "set_attrs", "key": key, "attrs": attrs}
        case _:
            return {"op": type(op).__name__}


@dataclass(frozen=True)
class SurfaceError(Exception):
    """操作面层失败：哪条 surface op、它被展开成了什么、为什么。

    - ``stage``：``"degrade"`` 或 ``"apply"``。
    - ``surface_index``：失败的 SurfaceOp 在 patch 中的序号（0 起）。
    - ``position``：该 SurfaceOp 在 patch 文本中的行号区间。
    - ``expanded``：该 SurfaceOp 展开出的 core ops（降解失败时为空）。
    - ``cause``：apply 失败为 ``OpError.reason``
      （``KEY_NOT_FOUND`` / ``BAD_ANCHOR`` 等机器可判读原因码）；降解失败
      一般为 ``None``，``replace`` 的 ``old`` 未出现时例外：
      ``PATTERN_NOT_FOUND``。
    """

    stage: str
    surface_index: int
    position: LineSpan
    expanded: tuple[Op, ...]
    cause: str | None
    message: str

    def __str__(self) -> str:
        start, end = self.position
        where = f"line {start}" if start == end else f"lines {start}-{end}"
        return (
            f"{self.stage} failed at surface op[{self.surface_index}] "
            f"({where}): {self.message}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "surface",
            "stage": self.stage,
            "surface_index": self.surface_index,
            "position": [self.position[0], self.position[1]],
            "expanded": [op_to_dict(op) for op in self.expanded],
            "cause": self.cause,
            "message": self.message,
        }
