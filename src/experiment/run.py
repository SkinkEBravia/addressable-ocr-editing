"""experiment 的执行矩阵：dataset × toolset × model。

对应 Docs/Design/11-experiment.md「运行配置」「公平性」「对话录」节。

- 同一实验内所有工具配置共用同一模型配置与预算口径（公平性）。
- resume 的键 = (task_id, toolset, config_hash)；配置变了即重跑。
- 每轮增量落盘；LLMError 级别失败 => status=failed，回退原文。
- workers > 1 时按 cell 并发（线程池）；并发只改变完成顺序，
  不改变任何 cell 的语义与落盘内容。进程内共享 client：适配器每次调用
  自建 httpx.Client，线程安全。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from datasetkit import load_dataset, select
from llm import LLMClient, LLMError, load_env_file
from toolsets import LoopResult, run_toolset

from experiment.config import (
    ToolsetConfig,
    build_toolset,
    config_hash,
)
from experiment.progress import NullProgress
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
    workers: int = 1,
    progress: Any = None,
) -> RunSummary:
    """执行矩阵。返回汇总；对话录逐轮落盘于 out/raw/。

    instruction 缺省用数据集的 default_instruction()。
    workers 为并发路数（默认 1，串行）。
    """
    load_env_file()  # 项目 .env 先进进程环境（幂等）
    progress = progress or NullProgress()
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

    cells: list[tuple[Any, ToolsetConfig, Any, str]] = []  # (task, cfg, toolset, cfg_hash)
    for cfg in toolset_configs:
        toolset = build_toolset(cfg)
        cfg_hash = config_hash(
            {"toolset": cfg.as_dict()},
            {"model": model_config_dict},
            {"instruction": instruction},
            dataset_params,
        )
        for task in tasks:
            cells.append((task, cfg, toolset, cfg_hash))

    progress.begin(len(cells))
    summary = RunSummary()

    def run_cell(cell: tuple[Any, ToolsetConfig, Any, str]) -> None:
        task, cfg, toolset, cfg_hash = cell
        label = f"{task.task_id} × {cfg.name}"
        writer = TranscriptWriter(out, task.task_id, cfg.name, cfg_hash)
        if writer.config_hash_matches():
            summary[str((task.task_id, cfg.name))] = "resumed"
            progress.end_cell(label, "resumed", None, 0.0)
            return
        workdir = out / "work" / task.task_id / cfg.name
        workdir.mkdir(parents=True, exist_ok=True)
        progress.start_cell(label)
        t0 = time.monotonic()

        def on_turn(turn, turns, _w=writer):
            _w.write_turn(turn, turns)
            progress.turn(turn.completion.usage)

        # 流式观察通道（搁置）：报告器声明了 delta 才接入，否则非流式请求
        on_delta = getattr(progress, "delta", None)

        try:
            result = run_toolset(
                client,
                task,
                toolset,
                cfg.budget(),
                instruction,
                workdir,
                on_turn=on_turn,
                on_delta=on_delta,
            )
            status = result.status
        except LLMError as exc:
            result = LoopResult(
                output=task.input,  # 失败回退原文
                status="failed",
                turns=(),
                total_usage=None,
            )
            status = f"failed:{exc.kind}"  # 事件行带失败类别
        writer.finalize(result, list(result.turns))
        summary[str((task.task_id, cfg.name))] = result.status
        progress.end_cell(label, status, result.total_usage, time.monotonic() - t0)

    if workers <= 1:
        for cell in cells:
            run_cell(cell)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(run_cell, cells))
    return summary
