"""experiment_app：HIPE-OCRepair 测评装配层（blocr vs blocr+system）。

设计规格见 Docs/Design/08-eval-framework.md。只经公开接口使用
llm / sourceio / partition / ir / reconstruction / view / surface。
"""

from experiment_app.arm_config import ArmConfig, build_arm, load_arm_config
from experiment_app.arms import (
    ArmResult,
    arm_noop,
    arm_patch,
    arm_rewrite,
    arm_rewrite_pieces,
)
from experiment_app.datasets import Sample, load_samples
from experiment_app.run import RunRecord, SampleArmRecord, run_experiment

__all__ = [
    "Sample",
    "load_samples",
    "ArmConfig",
    "load_arm_config",
    "build_arm",
    "ArmResult",
    "arm_noop",
    "arm_rewrite",
    "arm_patch",
    "arm_rewrite_pieces",
    "RunRecord",
    "SampleArmRecord",
    "run_experiment",
]
