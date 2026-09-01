"""evalkit：任务无关的评测公共组件库（Docs/Design/10-datasets.md）。

不认识任何具体数据集；数据集专有逻辑归各 dataset.py。
"""

from evalkit.stats import bootstrap_ci, paired_diff_ci
from evalkit.usage import output_ratio, sum_usage

__all__ = ["bootstrap_ci", "paired_diff_ci", "sum_usage", "output_ratio"]
