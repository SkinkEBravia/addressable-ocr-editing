"""evalkit.usage：多轮 Usage 合计与配对 output_ratio。

对应 Docs/Design/10-datasets.md「公共组件库 evalkit」节。
"""

from __future__ import annotations

from collections.abc import Sequence

from llm import Usage

__all__ = ["sum_usage", "output_ratio"]


def sum_usage(usages: Sequence[Usage | None]) -> Usage | None:
    """多轮 usage 合计；任一轮缺失则整体 None（usage_missing）。"""
    total_in = total_out = 0
    reasoning: int | None = 0
    for u in usages:
        if u is None:
            return None
        total_in += u.input_tokens
        total_out += u.output_tokens
        if u.reasoning_tokens is None:
            reasoning = None
        elif reasoning is not None:
            reasoning += u.reasoning_tokens
    return Usage(total_in, total_out, reasoning)


def output_ratio(numerator: Usage | None, denominator: Usage | None) -> float | None:
    """配对 output_ratio = 前者 tokens_out / 后者 tokens_out；缺失或除零为 None。"""
    if numerator is None or denominator is None or denominator.output_tokens == 0:
        return None
    return numerator.output_tokens / denominator.output_tokens
