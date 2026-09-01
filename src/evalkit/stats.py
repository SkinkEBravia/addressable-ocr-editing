"""evalkit.stats：任务无关的统计原语（bootstrap CI、配对差值）。

对应 Docs/Design/10-datasets.md「公共组件库 evalkit」节。
"""

from __future__ import annotations

import random
from collections.abc import Sequence

__all__ = ["bootstrap_ci", "paired_diff_ci"]


def bootstrap_ci(
    values: Sequence[float], *, resamples: int = 1000, seed: int = 0
) -> tuple[float, float, float]:
    """均值的 bootstrap 95% CI：(mean, lo, hi)。固定种子，可复现。"""
    if not values:
        raise ValueError("bootstrap_ci: empty values")
    n = len(values)
    mean = sum(values) / n
    if n == 1:
        return (mean, mean, mean)
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(resamples):
        estimates.append(sum(rng.choice(values) for _ in range(n)) / n)
    estimates.sort()
    lo = estimates[int(0.025 * resamples)]
    hi = estimates[min(int(0.975 * resamples), resamples - 1)]
    return (mean, lo, hi)


def paired_diff_ci(
    a: Sequence[float], b: Sequence[float], *, resamples: int = 1000, seed: int = 0
) -> tuple[float, float, float]:
    """配对差值 a - b 的 bootstrap 95% CI（同长度、逐位配对）。"""
    if len(a) != len(b):
        raise ValueError("paired_diff_ci: 长度不一致，无法配对")
    return bootstrap_ci([x - y for x, y in zip(a, b)], resamples=resamples, seed=seed)
