"""标准工具配置：patch（本系统 IR 操作面，fn 方言）。

对应 Docs/Design/09-tools.md「标准工具配置」节；操作面见 07-agent-api.md。

- 只经本系统公开接口（05/06/07）使用 IR，不 import 内部。
- agent 对块的定位一律用 AgentBlockId；BlockKey 不出现在对话中
  （默认策略 blockkey-as-is 下两者同形，但语义上是 Agent 侧 id）。
- 方言：assistant 消息整体即一段 fn patch；``done()`` 单独一行 = Done；
  ``view()`` 单独一行 = 重新拉取当前视图。
"""

from __future__ import annotations

from pathlib import Path

import ir
import partition
import reconstruction
import sourceio
import surface
import view as view_mod
from toolsets.core import DONE, Done, ToolCall, ToolContext, ToolParseError, ToolResult

__all__ = ["PatchToolSet", "PATCH_CLAUSE"]

PATCH_CLAUSE = """\
The text is shown as an annotated view in which each block is marked as:

<x id="bN"\\>
block content (verbatim, unescaped)
</x>

(the "\\>" in the opening tag is intentionally not well-formed XML.)

Do NOT rewrite the whole text. Express your corrections as a patch in the fn dialect: one function call per line, using these seven operations:
- replace(id, "old", "new") — replace every occurrence of "old" inside block id with "new". PREFERRED for sparse errors: fix only the wrong fragment and leave the rest of the block untouched. Rules: "old" must be copied VERBATIM from the block (if it does not occur exactly, the patch fails); every occurrence of "old" in the block will change, so keep "old" as SHORT as possible while still unambiguous — every character you quote costs output tokens
- set_content(id, "text") — replace the whole content of block id; use only when most of the block changes
- set_attrs(id, {...}) — replace the attrs object of block id (rarely needed)
- append(anchor, "text") — insert a new block after block anchor (anchor may be HEAD for the document start); optional third argument for attrs
- remove(id) — remove block id
- move(id, anchor) — move block id to after anchor
- merge(a, b) — append b's content to a and remove b

ids must be the ids shown in the annotations (or HEAD, only as an anchor). Strings and attrs objects use JSON syntax. Blank lines and lines starting with # are ignored.
After a successful patch you receive the affected blocks re-rendered; you may then emit another patch. When the text is fully corrected, output a single line:
done()
To re-fetch the current annotated view, output a single line:
view()
Otherwise output ONLY the patch. No explanation, no preamble, no markdown fences. If no correction is needed, output done() immediately."""


class PatchToolSet:
    """本系统块补丁工具集：view / run_patch 两个工具，fn 方言。"""

    name = "patch"
    uses_llm = True
    prompt_clause = PATCH_CLAUSE

    def __init__(self, partition_kind: str = "lines", block_size: int = 400) -> None:
        if partition_kind not in ("lines", "chars"):
            raise ValueError(f"unknown partition: {partition_kind!r}")
        self._partition_kind = partition_kind
        self._block_size = block_size

    # -- ToolSet 契约 -----------------------------------------------------

    def make_context(self, task_input: str, task_meta: dict, workdir: Path) -> ToolContext:
        store = ir.Store(workdir / "session")
        source = sourceio.SourceText(text=task_input, encoding="utf-8", bom=b"")
        if self._partition_kind == "lines":
            result = partition.partition_lines(source)
        else:
            result = partition.partition_chars(source, self._block_size)
        snapshot = ir.birth(source, result)
        ir.save(store, snapshot)
        ctx = ToolContext(workdir=workdir, data={"store": store})
        ctx.data["payload"] = self._render(ctx)
        return ctx

    def present_input(self, task_input: str, ctx: ToolContext) -> str:
        return ctx.data["payload"]

    def parse(self, text: str) -> "tuple[ToolCall, ...] | Done":
        stripped = text.strip()
        if not stripped:
            raise ToolParseError("empty response; emit a patch, view(), or done()")
        if stripped == "done()":
            return DONE
        if stripped == "view()":
            return (ToolCall("view"),)
        return (ToolCall("run_patch", text),)

    def invoke(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        if call.name == "view":
            payload = self._render(ctx)
            ctx.data["payload"] = payload
            return ToolResult(True, payload)
        if call.name == "run_patch":
            return self._apply_patch(call.args_text, ctx)
        return ToolResult(False, f"unknown tool: {call.name}")

    def extract(self, ctx: ToolContext) -> str:
        store: ir.Store = ctx.data["store"]
        snapshot = ir.load(store, ir.current(store))
        return reconstruction.reconstruct(snapshot).text

    # -- 内部 -------------------------------------------------------------

    def _render(self, ctx: ToolContext) -> str:
        store: ir.Store = ctx.data["store"]
        snapshot = ir.load(store, ir.current(store))
        agent_view = view_mod.present(
            snapshot, view_mod.blockkey_as_is, view_mod.xml_ish
        )
        return agent_view.payload

    def _apply_patch(self, patch_text: str, ctx: ToolContext) -> ToolResult:
        store: ir.Store = ctx.data["store"]
        try:
            result = surface.run_patch(
                store, patch_text, view_mod.blockkey_as_is, view_mod.xml_ish
            )
        except surface.ParseError as exc:
            return ToolResult(False, f"parse error at line {exc.line}: {exc.reason}")
        except surface.SurfaceError as exc:
            start, end = exc.position
            where = f"line {start}" if start == end else f"lines {start}-{end}"
            detail = f" ({exc.cause})" if exc.cause else ""
            return ToolResult(
                False,
                f"patch failed ({exc.stage}) at surface op {exc.surface_index} "
                f"[{where}]{detail}: {exc.message}",
            )
        parts = [f"patch applied; new snapshot: {result.snapshot_id}"]
        if not result.affected:
            parts.append("affected: none")
        for ab in result.affected:
            parts.append(f"[{ab.status}] {ab.agent_id}")
            if ab.annotated is not None:
                parts.append(ab.annotated.rstrip("\n"))
        return ToolResult(True, "\n".join(parts))
