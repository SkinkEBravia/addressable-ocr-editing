"""标准工具配置：rewrite_seq / patch_seq（逐单元顺序修复，一文档一场对话）。

对应 Docs/Design/09-tools.md「标准工具配置」节。

- 一个文档 = 一场多轮对话：每轮呈现一个单元（chunk），模型响应该单元的
  修复（rewrite = 重写文本；patch = fn patch），对话轮数 = 单元数。
- **无反馈口径**：模型每轮只看到下一个单元的呈现；工具结果与错误不回灌
  （对齐 rewrite「无多余返回信息」的口径）。parse 因此永不抛错——任何
  响应都视为该单元的提交；patch 的方言/应用错误在 invoke 内吞掉，该单元
  保留原文。分析走 replay 重 fold（磁带里有完整 patch 文本）。
- 终止：最后一个单元的 invoke 返回 ``ToolResult(finish=True)``。
- 每个单元只修复一次（单机会语义）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import ir
import partition
import reconstruction
import sourceio
import surface
import view as view_mod
from agent.assembly import format_input
from agent.patch import patch_clause
from agent.session import Session
from agent.standard import REWRITE_CLAUSE, extract_rewrite_text
from agent.toolset import ToolCall, ToolResult
from sourceio import SourceText

__all__ = ["RewriteSeqToolSet", "PatchSeqToolSet", "SEQ_REWRITE_CLAUSE"]

DOC_SEPARATOR = "\n"
"""单元拼接分隔符（与数据集装载一致）。"""


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


SEQ_REWRITE_CLAUSE = """\
The text arrives one part at a time. Correct EACH part as it arrives, using the output format below.

""" + REWRITE_CLAUSE
"""rewrite_seq 的条款：逐部分顺序修复，输出格式与 rewrite 一致。"""


def _source(text: str) -> SourceText:
    return SourceText(text=text, encoding="utf-8", bom=b"")


class RewriteSeqToolSet:
    """逐单元顺序重写：每轮 submit 一个单元的重写文本（JSON 条款）。"""

    name = "rewrite_seq"
    uses_llm = True
    prompt_clause = SEQ_REWRITE_CLAUSE

    # -- ToolSet 契约 -----------------------------------------------------

    def make_tool_state(
        self, task_input: str, task_meta: dict, workdir: Path
    ) -> dict[str, Any]:
        chunks = _split_units(task_input, task_meta.get("unit_boundaries"))
        return {"chunks": chunks, "outputs": [], "index": 0, "meta": task_meta}

    def present_input(self, task_input: str, tool_state: dict) -> str:
        return tool_state["chunks"][0]

    def parse(self, text: str) -> tuple[ToolCall, ...]:
        # 无反馈口径：任何响应都视为该单元的提交，parse 永不抛错
        return (ToolCall("submit", text),)

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        if call.name != "submit":
            return ToolResult(False, f"unknown tool: {call.name}")
        tool_state["outputs"].append(extract_rewrite_text(call.args_text))
        tool_state["index"] += 1
        return self._advance(tool_state)

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        # 预算截断等早退场景：未处理的单元回退原文
        outputs = list(tool_state["outputs"]) + list(
            tool_state["chunks"][len(tool_state["outputs"]):]
        )
        return _source(DOC_SEPARATOR.join(outputs))

    # -- 内部 -------------------------------------------------------------

    def _advance(self, tool_state: dict) -> ToolResult:
        index = tool_state["index"]
        chunks = tool_state["chunks"]
        if index >= len(chunks):
            return ToolResult(True, "", finish=True)
        # 下一轮 user 消息 = 下一个单元的呈现（与首条同一包装口径）
        return ToolResult(
            True, format_input(chunks[index], tool_state["meta"])
        )


class PatchSeqToolSet:
    """逐单元顺序 patch：每个单元独立的 IR 会话（块 id 每单元重排）。"""

    name = "patch_seq"
    uses_llm = True

    def __init__(
        self,
        partition_kind: str = "lines",
        block_size: int = 400,
        *,
        apply_mode: str = surface.APPLY_ATOMIC,
        hidden_ops: frozenset[str] = frozenset(),
    ) -> None:
        if partition_kind not in ("lines", "chars"):
            raise ValueError(f"unknown partition: {partition_kind!r}")
        if apply_mode not in (surface.APPLY_ATOMIC, surface.APPLY_BEST_EFFORT):
            raise ValueError(f"unknown apply_mode: {apply_mode!r}")
        self._partition_kind = partition_kind
        self._block_size = block_size
        self._apply_mode = apply_mode
        self.prompt_clause = patch_clause(hidden_ops, sequential=True)

    # -- ToolSet 契约 -----------------------------------------------------

    def make_tool_state(
        self, task_input: str, task_meta: dict, workdir: Path
    ) -> dict[str, Any]:
        chunks = _split_units(task_input, task_meta.get("unit_boundaries"))
        stores = []
        for i, chunk in enumerate(chunks):
            store = ir.Store(workdir / f"unit_{i}" / "session")
            source = sourceio.SourceText(text=chunk, encoding="utf-8", bom=b"")
            if self._partition_kind == "lines":
                result = partition.partition_lines(source)
            else:
                result = partition.partition_chars(source, self._block_size)
            ir.save(store, ir.birth(source, result))
            stores.append(store)
        return {"stores": stores, "index": 0, "meta": task_meta}

    def present_input(self, task_input: str, tool_state: dict) -> str:
        return self._render(tool_state["stores"][0])

    def parse(self, text: str) -> tuple[ToolCall, ...]:
        # 无反馈口径：任何响应都视为该单元的 patch 提交，parse 永不抛错
        return (ToolCall("run_patch", text),)

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        if call.name != "run_patch":
            return ToolResult(False, f"unknown tool: {call.name}")
        store = tool_state["stores"][tool_state["index"]]
        try:
            surface.run_patch(
                store,
                call.args_text,
                view_mod.blockkey_as_is,
                view_mod.xml_ish,
                mode=self._apply_mode,
            )
        except (surface.ParseError, surface.SurfaceError):
            pass  # 单机会语义：该单元保留原文；错误不回灌（口径对齐 rewrite_seq）
        tool_state["index"] += 1
        index = tool_state["index"]
        stores = tool_state["stores"]
        if index >= len(stores):
            return ToolResult(True, "", finish=True)
        return ToolResult(
            True, format_input(self._render(stores[index]), tool_state["meta"])
        )

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        texts = [
            reconstruction.reconstruct(ir.load(store, ir.current(store))).text
            for store in tool_state["stores"]
        ]
        return _source(DOC_SEPARATOR.join(texts))

    # -- 内部 -------------------------------------------------------------

    def _render(self, store: ir.Store) -> str:
        snapshot = ir.load(store, ir.current(store))
        agent_view = view_mod.present(
            snapshot, view_mod.blockkey_as_is, view_mod.xml_ish
        )
        return agent_view.payload
