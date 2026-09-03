"""agent 的 Session：一次 (task, toolset) 对话的运行时状态与磁带数据。

对应 Docs/Design/09-tools.md「Session」节。

- 运行时状态与落盘磁带是同一个结构（序列化归 experiment 的 store，
  序列化时剥掉 tool_state 即磁带）。
- 预设成员 = 跨工具集契约；tool_state 归工具集私有，loop 不读写。
- usage 派生自各轮 completion.usage；任一轮缺失则整体 None（usage_missing）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.toolset import Budget, ToolCall, ToolResult
from llm import Completion, Failure, Message, Usage

__all__ = ["Turn", "Session", "TAPE_VERSION"]

TAPE_VERSION = 1
"""磁带格式版本。演进时 +1，读取方按版本解释。"""


@dataclass(frozen=True)
class Turn:
    """一轮的完整记录（磁带落盘的单元）。"""

    index: int
    request: tuple[Message, ...]  # 落盘：全文按内容哈希去重存 messages/
    completion: Completion
    calls: tuple[ToolCall, ...] = ()
    results: tuple[ToolResult, ...] = ()  # 与 calls 对齐
    parse_error: str | None = None


@dataclass
class Session:
    """一次对话的全部状态。loop 就地修改（turns 追加、status/failure/output 赋值）。"""

    task_id: str
    toolset: str  # 工具配置名（报告标签）
    config_hash: str  # resume 键的一部分，由 experiment 计算
    budget: Budget
    turns: list[Turn] = field(default_factory=list)  # append-only
    status: str = "running"  # running | done | budget_exceeded | failed:<kind>
    failure: Failure | None = None  # 挂在 Session 而非 Turn——turn-0 失败时 turns 为空
    output: str | None = None  # extract 产出的 text；失败回退原文；cell 结束时必有值
    tool_state: dict = field(default_factory=dict)  # 工具集私有；运行期专属，不落盘

    @property
    def usage(self) -> Usage | None:
        """各轮 usage 合计（含失败轮）；任一轮缺失则整体 None。"""
        total_in = total_out = 0
        reasoning: int | None = 0
        for t in self.turns:
            u = t.completion.usage
            if u is None:
                return None
            total_in += u.input_tokens
            total_out += u.output_tokens
            if u.reasoning_tokens is None:
                reasoning = None
            elif reasoning is not None:
                reasoning += u.reasoning_tokens
        return Usage(total_in, total_out, reasoning)
