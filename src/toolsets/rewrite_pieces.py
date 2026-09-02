"""标准工具配置：rewrite_pieces（逐单元重写后拼接，doc 粒度的归因参照）。

对应 Docs/Design/09-tools.md「标准工具配置」节。

隔离「文档变长对重写质量的影响」与「工具集的差异」：输入按
task.meta["unit_boundaries"] 切回单元，逐单元独立重写（每单元一条全新
对话），结果按同一分隔符拼接。无 unit_boundaries 时退化为单单元（= rewrite）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llm import LLMClient, Message
from toolsets.basic import REWRITE_CLAUSE, extract_rewrite_text
from toolsets.core import (
    Budget,
    Done,
    LoopResult,
    ToolCall,
    ToolContext,
    ToolResult,
    TurnRecord,
    _sum_usage,
    build_initial_messages,
)

__all__ = ["RewritePiecesToolSet"]

DOC_SEPARATOR = "\n"
"""单元拼接分隔符（与数据集装载一致）。"""


class RewritePiecesToolSet:
    """逐单元重写后拼接；自定义 runner（每单元一轮独立对话）。"""

    name = "rewrite_pieces"
    uses_llm = True
    prompt_clause = REWRITE_CLAUSE

    # -- ToolSet 契约（loop 路径不会用到，仅为契约完整） -------------------

    def make_context(self, task_input: str, task_meta: dict, workdir: Path) -> ToolContext:
        return ToolContext(workdir=workdir)

    def present_input(self, task_input: str, ctx: ToolContext) -> str:
        return task_input

    def parse(self, text: str) -> "tuple[ToolCall, ...] | Done":
        from toolsets.core import DONE

        return DONE

    def invoke(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        return ToolResult(False, f"unknown tool: {call.name}")

    def extract(self, ctx: ToolContext) -> str:
        return ctx.data.get("last_text", "")

    # -- 自定义 runner -----------------------------------------------------

    def run(
        self,
        client: LLMClient,
        task: Any,
        budget: Budget,
        instruction: str,
        workdir: Path,
        on_turn: "Any | None" = None,
        on_delta: "Any | None" = None,
    ) -> LoopResult:
        units = _split_units(task.input, task.meta.get("unit_boundaries"))
        outputs: list[str] = []
        turns: list[TurnRecord] = []
        status = "done"
        for unit in units:
            if len(turns) >= budget.max_turns * len(units):
                status = "budget_exceeded"
                outputs.append(unit)  # 未处理的单元回退原文
                continue
            messages = build_initial_messages(
                instruction, REWRITE_CLAUSE, unit, task.meta
            )
            completion = client.complete(messages, on_delta=on_delta)
            record = TurnRecord(len(turns), tuple(messages), completion, ())
            turns.append(record)
            if on_turn is not None:
                on_turn(record, turns)
            outputs.append(extract_rewrite_text(completion.text))
        return LoopResult(
            output=DOC_SEPARATOR.join(outputs),
            status=status,
            turns=tuple(turns),
            total_usage=_sum_usage(turns),
        )


def _split_units(text: str, boundaries: Any) -> tuple[str, ...]:
    """按 unit_boundaries（各单元起始偏移）切回单元；无则整体为单单元。"""
    if not boundaries or not isinstance(boundaries, (list, tuple)) or len(boundaries) < 2:
        return (text,)
    units: list[str] = []
    for i, start in enumerate(boundaries):
        if i + 1 < len(boundaries):
            end = boundaries[i + 1] - len(DOC_SEPARATOR)
        else:
            end = len(text)
        units.append(text[start:end])
    return tuple(units)
