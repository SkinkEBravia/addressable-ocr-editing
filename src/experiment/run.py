"""experiment 的执行矩阵：dataset × toolset × model。

对应 Docs/Design/11-experiment.md「运行配置」「公平性」「对话录」节。

- 同一实验内所有工具配置共用同一模型配置与预算口径（公平性）。
- resume 的键 = (task_id, toolset, config_hash)；配置变了即重跑。
- 每轮增量落盘；LLMError 级别失败 => status=failed，回退原文。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from datasetkit import load_dataset, select
from llm import LLMClient, LLMError, load_env_file
from toolsets import LoopResult, run_toolset

from experiment.config import (
    ToolsetConfig,
    build_toolset,
    config_hash,
)
from experiment.transcript import TranscriptWriter

__all__ = ["run_experiment", "RunSummary"]


class RunSummary(dict):
    """(task_id, toolset) -> status 的简易汇总。"""


def run_experiment(
    *,
    dataset_dir: Path,
    toolset_configs: list[ToolsetConfig],
    client: LLMClient,
    model_config_dict: dict,
    split: str,
    granularity: str | None = None,
    ids: list[str] | None = None,
    languages: list[str] | None = None,
    limit: int | None = None,
    instruction: str | None = None,
    out: Path,
    on_progress: Callable[[str], None] | None = None,
) -> RunSummary:
    """执行矩阵。返回汇总；对话录逐轮落盘于 out/raw/。

    instruction 缺省用数据集的 default_instruction()。
    """
    load_env_file()  # 项目 .env 先进进程环境（幂等）
    dataset = load_dataset(dataset_dir)
    tasks = list(
        select(
            dataset,
            split=split,
            granularity=granularity,
            ids=ids,
            languages=languages,
            limit=limit,
        )
    )
    instruction = instruction if instruction is not None else dataset.default_instruction()

    dataset_params = {
        "dataset_dir": str(Path(dataset_dir).resolve()),
        "split": split,
        "granularity": granularity,
        "ids": ids,
        "languages": languages,
        "limit": limit,
    }

    summary = RunSummary()
    for cfg in toolset_configs:
        toolset = build_toolset(cfg)
        cfg_hash = config_hash(
            {"toolset": cfg.as_dict()},
            {"model": model_config_dict},
            {"instruction": instruction},
            dataset_params,
        )
        for task in tasks:
            key = (task.task_id, cfg.name)
            writer = TranscriptWriter(out, task.task_id, cfg.name, cfg_hash)
            if writer.config_hash_matches():
                summary[str(key)] = "resumed"
                if on_progress:
                    on_progress(f"skip (resume): {task.task_id} × {cfg.name}")
                continue
            workdir = out / "work" / task.task_id / cfg.name
            workdir.mkdir(parents=True, exist_ok=True)

            def on_turn(turn, turns, _w=writer):
                _w.write_turn(turn, turns)

            try:
                result = run_toolset(
                    client,
                    task,
                    toolset,
                    cfg.budget(),
                    instruction,
                    workdir,
                    on_turn=on_turn,
                )
            except LLMError as exc:
                result = LoopResult(
                    output=task.input,  # 失败回退原文
                    status="failed",
                    turns=(),
                    total_usage=None,
                )
                if on_progress:
                    on_progress(
                        f"failed: {task.task_id} × {cfg.name}: {exc.kind}: {exc}"
                    )
            writer.finalize(result, list(result.turns))
            summary[str(key)] = result.status
            if on_progress:
                on_progress(f"{result.status}: {task.task_id} × {cfg.name}")
    return summary
