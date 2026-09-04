"""experiment 的执行矩阵：dataset × toolset × model。

对应 Docs/Design/11-experiment.md「运行配置」「公平性」「磁带存储」节。

- 同一实验内所有工具配置共用同一模型配置与预算口径（公平性）。
- resume 的键 = (task_id, toolset, config_hash)；配置变了即重跑。
  failed:* 与 running（中断残留）一律重跑；done / budget_exceeded 跳过。
- 每轮增量落盘（SessionStore）；失败现场（Session.failure）随磁带持久。
- workers > 1 时按 cell 并发（线程池）。cell 之间无共享可变状态：
  每个 cell 独立 Session 与 workdir；client 无状态、每次调用自建连接。
  并发只改变完成顺序，不改变任何 cell 的语义与落盘内容。
"""

from __future__ import annotations

import dataclasses
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from agent import Session, ToolsetConfig, build_toolset, run_session, start_session
from datasetkit import load_dataset, resolve
from llm import LLMClient, load_env_file

from experiment.config import config_hash
from experiment.progress import NullProgress
from experiment.store import SessionStore

__all__ = ["run_experiment", "RunSummary"]


class RunSummary(dict):
    """(task_id, toolset) -> status 的简易汇总。"""


def run_experiment(
    *,
    dataset_dir: Path,
    toolset_configs: list[ToolsetConfig],
    client: LLMClient | None,  # None 仅当全部工具集不调 LLM
    model_config_dict: dict,
    split: str,
    loader_keys: list[str] | None = None,
    meta_filter: dict[str, str] | None = None,
    ids: list[str] | None = None,
    limit: int | None = None,
    instruction: str | None = None,
    out: Path,
    workers: int = 1,
    stream: bool = True,
    progress: Any = None,
) -> RunSummary:
    """执行矩阵。返回汇总；磁带逐轮落盘于 out/sessions/。

    instruction 缺省用数据集的 default_instruction()。
    workers 为并发路数（默认 1，串行）。stream 为流式观察开关（默认开）。
    """
    load_env_file()  # 项目 .env 先进进程环境（幂等）
    progress = progress or NullProgress()
    dataset = load_dataset(dataset_dir)
    tasks = list(
        resolve(
            dataset, split=split, keys=loader_keys, meta=meta_filter, ids=ids, limit=limit
        )
    )
    instruction = instruction if instruction is not None else dataset.default_instruction()

    dataset_params = {
        # 环境无关的相对形式：宿主与容器都从仓库根跑同一条命令时，
        # resume 键必须一致（否则换环境 = 静默全量重跑，血泪教训）
        "dataset_dir": str(Path(dataset_dir)),
        "split": split,
        "loader_keys": loader_keys,
        "meta": meta_filter,
        "ids": ids,
        "limit": limit,
    }
    # 过渡兼容：旧磁带用的是绝对路径配方；本机可重算的遗留哈希一并接受
    legacy_dataset_params = {
        **dataset_params,
        "dataset_dir": str(Path(dataset_dir).resolve()),
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
        legacy_hash = config_hash(
            {"toolset": cfg.as_dict()},
            {"model": model_config_dict},
            {"instruction": instruction},
            legacy_dataset_params,
        )
        for task in tasks:
            cells.append((task, cfg, toolset, cfg_hash, legacy_hash))

    progress.begin(len(cells))
    summary = RunSummary()
    store = SessionStore(out)
    # 流式观察：显式开关 + 报告器订阅者同时满足才接 delta
    on_delta = getattr(progress, "delta", None) if stream else None

    def run_cell(cell: tuple[Any, ToolsetConfig, Any, str, str]) -> None:
        task, cfg, toolset, cfg_hash, legacy_hash = cell
        label = f"{task.task_id} × {cfg.name}"
        old = store.resumable(task.task_id, cfg.name, cfg_hash, legacy=legacy_hash)
        if old is not None:
            summary[str((task.task_id, cfg.name))] = "resumed"
            # 事件行要显示 resumed 而非磁带上的旧终态（done/budget_exceeded）
            progress.end_cell(label, dataclasses.replace(old, status="resumed"), 0.0)
            return
        workdir = out / "work" / task.task_id / cfg.name
        session, messages = start_session(
            toolset,
            label=cfg.name,
            task_id=task.task_id,
            task_input=task.input,
            task_meta=task.meta,
            instruction=instruction,
            workdir=workdir,
            config_hash=cfg_hash,
            budget=cfg.budget(),
        )
        progress.start_cell(label)
        t0 = time.monotonic()
        store.write(session)  # 尽早落盘：running 态 / 组装期失败都可审计

        def on_turn(sess: Session) -> None:
            store.write(sess)
            progress.turn(sess)

        run_session(
            client,
            toolset,
            session,
            messages,
            fallback_text=task.input,
            on_turn=on_turn,
            on_delta=on_delta,
        )
        store.write(session)
        summary[str((task.task_id, cfg.name))] = session.status
        progress.end_cell(label, session, time.monotonic() - t0)

    if workers <= 1:
        for cell in cells:
            run_cell(cell)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(run_cell, cells))
    return summary
