"""experiment：实验装配层（Docs/Design/11-experiment.md）。

dataset × toolset × model 的执行矩阵；对话录落盘；replay；报告。
只经公开接口使用 llm / toolsets / datasetkit 与本系统，不 import 内部。
"""

from experiment.config import (
    ToolsetConfig,
    build_toolset,
    config_hash,
    load_toolset_config,
    toolset_config_from_dict,
)
from experiment.replay import replay
from experiment.report import build_report, write_report
from experiment.run import run_experiment

__all__ = [
    "ToolsetConfig",
    "load_toolset_config",
    "toolset_config_from_dict",
    "build_toolset",
    "config_hash",
    "run_experiment",
    "build_report",
    "write_report",
    "replay",
]
