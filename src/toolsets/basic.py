"""标准工具配置：noop / rewrite。

对应 Docs/Design/09-tools.md「标准工具配置」节。
"""

from __future__ import annotations

import json
from pathlib import Path

from toolsets.core import DONE, Done, ToolCall, ToolContext, ToolParseError, ToolResult

__all__ = ["NoopToolSet", "RewriteToolSet", "REWRITE_CLAUSE"]

# rewrite 的输出条款（BLOCR 原样：JSON 输出 + CORRECTIONS_CSV 日志，
# CSV 是 BLOCR 原样的 token 成本，保留）。
REWRITE_CLAUSE = """\
Return a JSON object with exactly one field: "ocr_postcorrection_output".
Return ONLY valid JSON. No explanation, no preamble, no markdown fences.

After the JSON object, output a CSV corrections log.
Marker line: CORRECTIONS_CSV
Columns: document_id,ocr_hypothesis_snippet,ocr_postcorrection_snippet,error_type,confidence,notes
- error_type: over_segmentation, misrecognized_char, under_segmentation, missing_character, wrong_word, uncertain, no_change, or custom:label
- confidence: high, medium, or low
- One row per document_id (use no_change if unchanged)
- Do not wrap the CSV in markdown fences"""


def extract_rewrite_text(text: str) -> str:
    """rewrite 产出提取：解析首个 JSON 对象的 ocr_postcorrection_output 字段
    （尾部 CORRECTIONS_CSV 日志忽略）；失败则剥 markdown 围栏；再失败用原文。"""
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.split("\n")
        lines = lines[1:] if len(lines) > 1 else lines
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    obj = None
    try:
        obj = json.loads(candidate)
    except ValueError:
        try:
            obj, _ = json.JSONDecoder().raw_decode(candidate)  # 首个 JSON 值，尾部忽略
        except ValueError:
            return text
    if isinstance(obj, dict) and isinstance(obj.get("ocr_postcorrection_output"), str):
        return obj["ocr_postcorrection_output"]
    return text


class NoopToolSet:
    """no-correction 锚点对照：不调 LLM，output = input。"""

    name = "noop"
    uses_llm = False
    prompt_clause = ""

    def make_context(self, task_input: str, task_meta: dict, workdir: Path) -> ToolContext:
        return ToolContext(workdir=workdir)

    def present_input(self, task_input: str, ctx: ToolContext) -> str:
        return task_input

    def parse(self, text: str) -> "tuple[ToolCall, ...] | Done":
        return DONE

    def invoke(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        return ToolResult(False, f"unknown tool: {call.name}")

    def extract(self, ctx: ToolContext) -> str:
        return ctx.data.get("last_text", "")


class RewriteToolSet:
    """空工具集：单轮全文重写，extract = 末轮 assistant 文本（解析 JSON 条款）。"""

    name = "rewrite"
    uses_llm = True
    prompt_clause = REWRITE_CLAUSE

    def make_context(self, task_input: str, task_meta: dict, workdir: Path) -> ToolContext:
        return ToolContext(workdir=workdir)

    def present_input(self, task_input: str, ctx: ToolContext) -> str:
        return task_input

    def parse(self, text: str) -> "tuple[ToolCall, ...] | Done":
        # 空工具集：任何响应都直接完成
        if not text.strip():
            raise ToolParseError("empty response")
        return DONE

    def invoke(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        return ToolResult(False, f"unknown tool: {call.name}")

    def extract(self, ctx: ToolContext) -> str:
        return extract_rewrite_text(ctx.data.get("last_text", ""))
