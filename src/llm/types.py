"""llm 的数据类型：Message / Usage / Completion / Turn。

对应 Docs/Design/08-llm.md「定义」节。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

__all__ = ["Role", "Message", "Usage", "Completion", "Turn"]

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    """一条对话消息。对话历史由调用方持有，client 无状态。"""

    role: Role
    content: str


@dataclass(frozen=True)
class Usage:
    """单次调用的 token 计数。

    契约：必须来自端点返回的 usage 字段，不做本地估算。
    reasoning_tokens 单列（思考 token 是成本比较的一部分）。
    """

    input_tokens: int
    output_tokens: int
    reasoning_tokens: int | None = None

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class Completion:
    """单次补全的结果。

    usage 为 None 表示端点未返回 usage（报告记 usage_missing）。
    raw 为端点原始响应（审计用）。
    elapsed_s 为本次调用的墙钟秒数（含重试前的等待不含），供 TPS 统计。
    """

    text: str
    usage: Usage | None
    raw: Any = None
    elapsed_s: float | None = None


@dataclass(frozen=True)
class Turn:
    """一轮对话的记录。"""

    index: int
    completion: Completion
