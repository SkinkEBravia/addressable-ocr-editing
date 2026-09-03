"""标准工具配置：swe_bash（SWE-agent 环境的忠实复刻：bash + PATH 上的 edit 脚本）。

对应 Docs/Design/09-tools.md「标准工具配置」节；参照
related_agents/swe-agent-classic（MIT，v0.7：edit 是容器内 PATH 上的 shell
脚本，模型只有一个 bash 入口）。

- 每个任务一个 workdir：内含 ``text.txt``（OCR 原文）与 ``bin/edit``
  （v0.7 语义的行号区间替换脚本）；调用时把 ``bin`` 前置进 PATH。
- ShellBackend 是可替换组件：当前为 ``GitBashBackend``（本机 Git Bash，
  Windows 可用）；``DockerBackend`` 留给有 Docker 的环境（真隔离）。
- **安全口径**：GitBashBackend 无沙箱——命令以当前用户身份在 workdir 下执行，
  仅用于可信实验输入；env 会剥掉 KEY/TOKEN/SECRET 类变量（不进子进程）。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Protocol

from agent.session import Session
from agent.toolset import DONE, Done, ToolCall, ToolParseError, ToolResult
from sourceio import SourceText

__all__ = ["SweBashToolSet", "ShellBackend", "GitBashBackend", "SWE_BASH_CLAUSE"]

_OUTPUT_LIMIT = 4000
_TIMEOUT_S = 30.0

# v0.7 语义：edit <start_line>:<end_line>，替换文本从 stdin 读到 end_of_edit
_EDIT_SCRIPT = """#!/usr/bin/env bash
# edit <start_line>:<end_line> — replaces lines <start_line> through <end_line>
# (inclusive) in $FILE (default text.txt). The replacement text is read from
# stdin, terminated by a line with only end_of_edit on it.
set -u
FILE="${FILE:-text.txt}"
usage() { echo "Usage: edit <start_line>:<end_line>"; exit 1; }
[ $# -ge 1 ] || usage
start_line="$(echo "$1" | cut -d: -f1)"
end_line="$(echo "$1" | cut -d: -f2)"
re='^[0-9]+$'
[[ $start_line =~ $re ]] || usage
[[ $end_line =~ $re ]] || usage
total=$(awk 'END {print NR}' "$FILE")
if [ "$start_line" -lt 1 ] || [ "$end_line" -gt "$total" ] || [ "$start_line" -gt "$end_line" ]; then
  echo "Invalid line range $start_line:$end_line (file has $total lines)"
  exit 1
fi
replacement=$(cat)  # heredoc 终结行由 shell 剥离，stdin 即替换文本
{ head -n $((start_line - 1)) "$FILE"; printf '%s\\n' "$replacement"; tail -n +$((end_line + 1)) "$FILE"; } > "$FILE.tmp"
mv "$FILE.tmp" "$FILE"
echo "Edit applied to $FILE."
"""

# 现行 SWE-agent（windowed_edit_replace）语义的字符串替换：replace-all
_REPLACE_SCRIPT = """#!/usr/bin/env bash
# replace <old> <new> — replace EVERY occurrence of <old> in $FILE (default
# text.txt) with <new>. Fails with PATTERN_NOT_FOUND if <old> does not occur.
set -u
FILE="${FILE:-text.txt}"
[ $# -eq 2 ] || { echo "Usage: replace <old> <new>"; exit 1; }
old="$1"; new="$2"
if ! grep -qF -- "$old" "$FILE"; then
  echo "PATTERN_NOT_FOUND: '$old' does not occur in $FILE"
  exit 1
fi
python - "$FILE" "$old" "$new" <<'PY'
import sys
path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(path, encoding="utf-8").read()
count = text.count(old)
open(path, "w", encoding="utf-8").write(text.replace(old, new))
print(f"replaced {count} occurrence(s)")
PY
"""

SWE_BASH_CLAUSE = """\
You are working directly in the command line with a special interface. The text to correct is in the file `text.txt` in your current directory.

In addition to typical bash commands (cat, grep, sed, awk, ...), you can use the following special command to edit the file:
edit <start_line>:<end_line> — replaces lines <start_line> through <end_line> (inclusive) in text.txt with the replacement text. The replacement text is read from stdin, terminated by a line with only end_of_edit on it. All of the replacement text will be entered literally, so make sure your whitespace is exact. Example:
edit 5:7 << end_of_edit
corrected line one
corrected line two
end_of_edit

replace <old> <new> — replace EVERY occurrence of <old> in text.txt with <new>. <old> must match the file content EXACTLY (verbatim); if it does not occur, the command fails with PATTERN_NOT_FOUND. Keep <old> as SHORT as possible while still unambiguous — every character you quote costs output tokens. Example:
replace "recorn mended" "recommended"

To run a command, output one function call per line:
bash("<your shell command here>")
The command string uses JSON syntax (escape newlines as \\n and quotes as \\"). Commands are non-interactive (no vim/python REPL); each runs with a 30s timeout.
When the text is fully corrected, output a single line:
done()
Output ONLY the calls. No explanation, no preamble, no markdown fences. If no correction is needed, output done() immediately."""


class ShellBackend(Protocol):
    """命令执行后端（可替换组件）：一条命令进，(exit_code, 输出) 出。"""

    def run(self, command: str, *, cwd: Path, env: dict, timeout: float) -> tuple[int, str]: ...


class GitBashBackend:
    """本机 Git Bash 后端（无沙箱；可信实验输入专用）。"""

    def __init__(self, bash_path: str | None = None) -> None:
        self._bash = (
            bash_path
            or shutil.which("bash")
            or (
                r"C:\Program Files\Git\bin\bash.exe"
                if Path(r"C:\Program Files\Git\bin\bash.exe").is_file()
                else None
            )
        )
        if self._bash is None:
            raise RuntimeError("找不到 bash（需要 Git Bash 或 DockerBackend）")

    def run(self, command: str, *, cwd: Path, env: dict, timeout: float) -> tuple[int, str]:
        try:
            proc = subprocess.run(
                [self._bash, "-c", command],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return 124, f"command timed out after {timeout:.0f}s"
        out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        if len(out) > _OUTPUT_LIMIT:
            out = out[:_OUTPUT_LIMIT] + f"\n...[truncated, {len(out)} chars total]"
        return proc.returncode, out


def _scrub_env(base: dict[str, str]) -> dict[str, str]:
    """剥掉疑似密钥的环境变量（不进子进程）。"""
    return {
        k: v
        for k, v in base.items()
        if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET"))
    }


class SweBashToolSet:
    """bash 单工具 + workdir 环境（text.txt + bin/edit）。"""

    name = "swe_bash"
    uses_llm = True
    prompt_clause = SWE_BASH_CLAUSE

    def __init__(self, backend: ShellBackend | None = None) -> None:
        self._backend = backend or GitBashBackend()

    # -- ToolSet 契约 -----------------------------------------------------

    def make_tool_state(
        self, task_input: str, task_meta: dict, workdir: Path
    ) -> dict[str, Any]:
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "text.txt").write_text(task_input, encoding="utf-8")
        bin_dir = workdir / "bin"
        bin_dir.mkdir(exist_ok=True)
        for name, content in (("edit", _EDIT_SCRIPT), ("replace", _REPLACE_SCRIPT)):
            script = bin_dir / name
            script.write_text(content, encoding="utf-8", newline="\n")  # bash 要 LF
            script.chmod(0o755)
        env = _scrub_env(dict(os.environ))
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
        return {"workdir": workdir, "env": env}

    def present_input(self, task_input: str, tool_state: dict) -> str:
        return task_input

    def parse(self, text: str) -> "tuple[ToolCall, ...] | Done":
        calls: list[ToolCall] = []
        for lineno, raw in enumerate(text.split("\n"), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line == "done()":
                if calls:
                    raise ToolParseError(
                        f"line {lineno}: done() must be the only content of a message"
                    )
                return DONE
            m = re.match(r'bash\s*\((.*)\)\s*\Z', line, re.DOTALL)
            if m is None:
                raise ToolParseError(
                    f"line {lineno}: expected `bash(\"cmd\")` or done(), got {line!r}"
                )
            import json

            try:
                command = json.JSONDecoder().raw_decode(m.group(1).strip())[0]
            except json.JSONDecodeError as exc:
                raise ToolParseError(f"line {lineno}: invalid JSON string: {exc.msg}")
            if not isinstance(command, str):
                raise ToolParseError(f"line {lineno}: bash argument must be a JSON string")
            calls.append(ToolCall("bash", command))
        if not calls:
            raise ToolParseError("empty response; emit bash(...) or done()")
        return tuple(calls)

    def invoke(self, call: ToolCall, tool_state: dict) -> ToolResult:
        if call.name != "bash":
            return ToolResult(False, f"unknown tool: {call.name}")
        code, out = self._backend.run(
            call.args_text,
            cwd=tool_state["workdir"],
            env=tool_state["env"],
            timeout=_TIMEOUT_S,
        )
        header = f"[exit {code}]"
        return ToolResult(code == 0, f"{header}\n{out}" if out else header)

    def extract(self, tool_state: dict, session: Session) -> SourceText:
        text = (tool_state["workdir"] / "text.txt").read_text(encoding="utf-8")
        return SourceText(text=text, encoding="utf-8", bom=b"")
