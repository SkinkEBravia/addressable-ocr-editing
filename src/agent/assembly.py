"""agent 的上下文组装：instruction + prompt_clause + 输入呈现 -> 初始 messages。

对应 Docs/Design/09-tools.md「组装上下文」节。

- system = instruction（属数据集）+ prompt_clause（属工具集），顺序固定、逐字拼接。
- 首条 user = 输入呈现的通用包装。
- 组装函数只有一个，loop 与任何多上下文变体共用。
"""

from __future__ import annotations

from llm import Message

__all__ = ["format_input", "build_initial_messages"]


def format_input(presented_input: str, task_meta: dict) -> str:
    """输入的通用包装：带语言（若有）的围栏块。"""
    language = task_meta.get("language")
    tag = f" (language: {language})" if isinstance(language, str) and language else ""
    return f"--- INPUT{tag} ---\n{presented_input}\n--- END OF INPUT ---"


def build_initial_messages(
    instruction: str,
    prompt_clause: str,
    presented_input: str,
    task_meta: dict,
) -> list[Message]:
    """提示词组装（拼接口径全实验一致）。"""
    return [
        Message("system", instruction + "\n\n" + prompt_clause),
        Message("user", format_input(presented_input, task_meta)),
    ]
