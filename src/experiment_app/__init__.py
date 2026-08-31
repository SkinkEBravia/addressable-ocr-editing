"""experiment_app：HIPE-OCRepair 测评装配层（blocr vs blocr+system）。

设计规格见 Docs/Design/08-eval-framework.md。只经公开接口使用
llm / sourceio / partition / ir / reconstruction / view / surface。
"""

from experiment_app.arms import (
    ArmResult,
    arm_blocr,
    arm_blocr_system,
    arm_noop,
    arm_ref_blocr_pieces,
)
from experiment_app.datasets import Sample, load_samples
from experiment_app.run import RunRecord, SampleArmRecord, run_experiment

__all__ = [
    "Sample",
    "load_samples",
    "ArmResult",
    "arm_noop",
    "arm_blocr",
    "arm_blocr_system",
    "arm_ref_blocr_pieces",
    "RunRecord",
    "SampleArmRecord",
    "run_experiment",
]
