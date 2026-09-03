"""experiment：实验装配——执行矩阵、磁带存储、评测与报告。

设计规格见 Docs/Design/11-experiment.md。
"""

from experiment.config import config_hash
from experiment.run import RunSummary, run_experiment
from experiment.store import SessionStore

__all__ = ["config_hash", "run_experiment", "RunSummary", "SessionStore"]
