"""toolsets 核心：Tool / ToolSet 契约、Budget、run_loop。

对应 Docs/Design/09-tools.md「定义」「Loop」节。

- 工具配置 = 工具集 + 方言 + 提示词条款 + 终止预算。
- 工具报错与 ParseError 走同一通道：作为 feedback 进下一轮，无独立重试机制。
- 提示词组装：system 消息 = instruction（属数据集）+ prompt_clause（属工具集），
  逐字拼接；首条 user 消息 = 输入呈现。
- agent 对块的定位一律用 AgentBlockId（见 06/07）；工具集不得把 BlockKey
  泄漏进对话。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from llm import Completion, LLMClient, Message, Usage

__all__ = [
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
    "format_input",
    "build_initial_messages",
]


@dataclass(frozen=True)
class ToolCall:
    name: str
    args_text: str = ""


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    feedback: str  # 原样作为 user 消息进下一轮


class Tool(Protocol):
    name: str

    def invoke(self, call: ToolCall, ctx: "ToolContext") -> ToolResult: ...


class Done:
    """parse 的返回标记：模型自判完成。"""

    def __repr__(self) -> str:  # pragma: no cover
        return "DONE"


DONE = Done()
"""Done 单例。"""


class ToolParseError(Exception):
    """方言解析失败；reason 作为 feedback 进下一轮。"""


@dataclass
class ToolContext:
    """工具的运行环境，每任务一份，由 loop 在任务开始时创建。"""

    workdir: Path
    data: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ToolSet(Protocol):
    """工具集四件套：tools / parse / prompt_clause / extract（+ 输入呈现）。"""

    name: str
    uses_llm: bool  # noop 为 False：不调 LLM，output = input
    prompt_clause: str  # 工具使用条款，逐字进提示词

    def make_context(self, task_input: str, task_meta: dict, workdir: Path) -> ToolContext: ...

    def present_input(self, task_input: str, ctx: ToolContext) -> str:
        """首条 user 消息中输入的呈现形式（patch = 标注视图；其余 = 原文）。"""
        ...

    def parse(self, text: str) -> "tuple[ToolCall, ...] | Done":
        """方言解析器：assistant 文本 -> 工具调用序列或 Done。

        解析失败抛 ToolParseError。
        """
        ...

    def invoke(self, call: ToolCall, ctx: ToolContext) -> ToolResult: ...

    def extract(self, ctx: ToolContext) -> str: ...


@dataclass(frozen=True)
class Budget:
    """终止预算；公平性控制的一部分，跨工具配置必须一致。"""

    max_turns: int = 1
    token_budget: int | None = None


@dataclass(frozen=True)
class TurnRecord:
    """一轮的完整记录（对话录落盘的单元）。"""

    index: int
    request: tuple[Message, ...]
    completion: Completion
    calls: tuple[tuple[ToolCall, ToolResult], ...] = ()
    parse_error: str | None = None


@dataclass(frozen=True)
class LoopResult:
    output: str
    status: str  # done | budget_exceeded | failed
    turns: tuple[TurnRecord, ...]
    total_usage: Usage | None  # 任一轮 usage 缺失则为 None（usage_missing）


def format_input(task_input: str, task_meta: dict) -> str:
    """输入的通用包装：带语言（若有）的围栏块。"""
    language = task_meta.get("language")
    tag = f" (language: {language})" if isinstance(language, str) and language else ""
    return f"--- INPUT{tag} ---\n{task_input}\n--- END OF INPUT ---"


def build_initial_messages(
    instruction: str,
    prompt_clause: str,
    presented_input: str,
    task_meta: dict,
) -> list[Message]:
    """提示词组装（09「Loop」规则 1）：system = instruction + prompt_clause
    （顺序固定、逐字拼接）；首条 user = 输入呈现。loop 与自定义 runner
    （rewrite_pieces 等）共用本函数，组装口径全局唯一。"""
    return [
        Message("system", instruction + "\n\n" + prompt_clause),
        Message("user", format_input(presented_input, task_meta)),
    ]


def _sum_usage(turns: list[TurnRecord]) -> Usage | None:
    """各轮 usage 合计（含失败轮）；任一轮缺失则整体 None。"""
    total_in = total_out = 0
    reasoning: int | None = 0
    for t in turns:
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


def run_loop(
    client: LLMClient,
    task_input: str,
    task_meta: dict,
    toolset: ToolSet,
    budget: Budget,
    instruction: str,
    workdir: Path,
    on_turn: "Any | None" = None,
    on_delta: "Any | None" = None,
) -> LoopResult:
    """多轮 agent loop。

    1. 首条 user 消息 = instruction + prompt_clause + 输入呈现（逐字拼接）。
    2. 每轮：complete -> parse -> 按序 invoke -> feedback 进下一轮；
       Done -> extract 结束。
    3. ParseError 与工具失败走同一通道（feedback 进下一轮）。
    4. 预算耗尽 -> budget_exceeded，仍 extract 产出。

    on_turn(TurnRecord, LoopResult 片段) 在每轮落盘后回调（增量落盘用）。
    """
    ctx = toolset.make_context(task_input, task_meta, workdir)

    if not toolset.uses_llm:  # noop：不调 LLM，output = input
        return LoopResult(
            output=task_input, status="done", turns=(), total_usage=Usage(0, 0, 0)
        )

    messages = build_initial_messages(
        instruction,
        toolset.prompt_clause,
        toolset.present_input(task_input, ctx),
        task_meta,
    )
    turns: list[TurnRecord] = []
    status = "budget_exceeded"  # 正常退出路径会覆盖

    while len(turns) < budget.max_turns:
        completion = client.complete(messages, on_delta=on_delta)  # LLMError 由调用方处理 -> failed
        ctx.data["last_text"] = completion.text
        messages.append(Message("assistant", completion.text))
        index = len(turns)

        try:
            outcome = toolset.parse(completion.text)
        except ToolParseError as exc:
            record = TurnRecord(index, tuple(messages[:-1]), completion, (), str(exc))
            turns.append(record)
            if on_turn is not None:
                on_turn(record, turns)
            messages.append(Message("user", f"parse error: {exc}"))
            continue

        if isinstance(outcome, Done):
            record = TurnRecord(index, tuple(messages[:-1]), completion, ())
            turns.append(record)
            if on_turn is not None:
                on_turn(record, turns)
            status = "done"
            break

        results: list[tuple[ToolCall, ToolResult]] = []
        feedbacks: list[str] = []
        for call in outcome:  # 同轮多调用按序，后续看到前面结果
            result = toolset.invoke(call, ctx)
            results.append((call, result))
            feedbacks.append(
                result.feedback if result.ok else f"error: {result.feedback}"
            )
        record = TurnRecord(index, tuple(messages[:-1]), completion, tuple(results))
        turns.append(record)
        if on_turn is not None:
            on_turn(record, turns)
        messages.append(Message("user", "\n".join(feedbacks)))

        usage = _sum_usage(turns)
        if (
            budget.token_budget is not None
            and usage is not None
            and usage.total > budget.token_budget
        ):
            break

    try:
        output = toolset.extract(ctx)
    except Exception:
        output = task_input  # extract 失败回退原文
        if status == "done":
            status = "failed"
    return LoopResult(
        output=output, status=status, turns=tuple(turns), total_usage=_sum_usage(turns)
    )


def run_toolset(
    client: LLMClient,
    task: "Any",
    toolset: ToolSet,
    budget: Budget,
    instruction: str,
    workdir: Path,
    on_turn: "Any | None" = None,
    on_delta: "Any | None" = None,
) -> LoopResult:
    """分派：工具集自带自定义 runner（如 rewrite_pieces）则用之，否则 run_loop。"""
    custom = getattr(toolset, "run", None)
    if callable(custom):
        return custom(
            client, task, budget, instruction, workdir, on_turn=on_turn, on_delta=on_delta
        )
    return run_loop(
        client, task.input, task.meta, toolset, budget, instruction, workdir,
        on_turn, on_delta,
    )
