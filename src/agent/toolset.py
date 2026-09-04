"""agent 的工具契约：ToolSet 四件套 + 输入呈现、Budget、方言错误。

对应 Docs/Design/09-tools.md「工具契约」节。

- 工具配置 = 工具集 + 方言 + 提示词条款 + 终止预算。
- 工具报错与 ToolParseError 走对话通道：作为 feedback 进下一轮，无独立重试。
- agent 对块的定位一律用 AgentBlockId（见 06/07）；工具集不得把 BlockKey
  泄漏进对话。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from sourceio import SourceText

if TYPE_CHECKING:
    from agent.session import Session

__all__ = [
    "ToolCall",
    "ToolResult",
    "ToolParseError",
    "Done",
    "DONE",
    "Budget",
    "ToolSet",
]


@dataclass(frozen=True)
class ToolCall:
    name: str
    args_text: str = ""


@dataclass(frozen=True)
class ToolResult:
    """领域错误用 ok=False 表达（进对话通道）；意外异常由 loop 捕获进失败通道。

    finish=True：工具侧宣告对话完成（顺序任务的自然终止——如逐单元修复的
    最后一个单元已处理）。loop 在本轮结束后以 done 收束，不再追加 feedback。
    """

    ok: bool
    feedback: str  # 原样作为 user 消息进下一轮
    finish: bool = False

    @property
    def output(self) -> str:
        return self.feedback


class ToolParseError(Exception):
    """方言解析失败；reason 作为 feedback 进下一轮。"""


class Done:
    """parse 的返回标记：模型自判完成。"""

    def __repr__(self) -> str:  # pragma: no cover
        return "DONE"


DONE = Done()
"""Done 单例。"""


@dataclass(frozen=True)
class Budget:
    """终止预算；公平性控制的一部分，跨工具配置必须一致。"""

    max_turns: int = 1
    token_budget: int | None = None


@runtime_checkable
class ToolSet(Protocol):
    """工具集契约：每个成员只被一个阶段消费（见 09 表）。

    - prompt_clause / present_input -> 组装上下文
    - parse / invoke -> loop（invoke 也被 replay 重 fold）
    - extract -> 工具应用（产出）
    """

    name: str
    uses_llm: bool  # noop 为 False：零轮迭代，output = input
    prompt_clause: str  # 工具使用条款，逐字进 system 消息

    def make_tool_state(
        self, task_input: str, task_meta: dict, workdir: Path
    ) -> dict[str, Any]:
        """构造运行环境（每 Session 一份）。返回的 dict 归工具集私有：
        loop / experiment 不得读写；不落盘。"""
        ...

    def present_input(self, task_input: str, tool_state: dict) -> str:
        """首条 user 消息中输入的呈现形式（patch = 标注视图；其余 = 原文）。"""
        ...

    def parse(self, text: str) -> "tuple[ToolCall, ...] | Done":
        """方言解析器：assistant 文本 -> 工具调用序列或 Done。失败抛 ToolParseError。"""
        ...

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        """工具 fold 的一步。同一 fold 内后续调用看到前面调用的结果。"""
        ...

    def extract(self, tool_state: dict, session: "Session") -> SourceText:
        """fold 末态 -> 产出文件。rewrite 的 fold 状态即对话本身（读 session.turns）。"""
        ...
