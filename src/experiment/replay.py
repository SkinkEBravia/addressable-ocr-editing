"""experiment 的 replay：改动只涉确定性后处理时免重跑 LLM。

对应 Docs/Design/11-experiment.md「replay」节。

- 按对话录逐轮重放后处理（parse / invoke / extract），token 沿用记录值。
- prompt / 模型 / 工具集变了 => replay 无效，必须重跑。
- 新代码下某轮后处理失败而磁带没有下一轮 => 按 failed 回退原文
  （真实重跑的下界），报告注明。
- 配置从旧 report.json 读回，不用当前 configs/ 下的同名文件。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from datasetkit import load_dataset, resolve
from toolsets import Done, ToolParseError

from experiment.config import build_toolset, toolset_config_from_dict

__all__ = ["replay"]


def _replay_one(toolset: Any, task: Any, turns: list[dict], workdir: Path) -> tuple[str, bool]:
    """重放一个 (task, toolset)；返回 (output, lower_bound)。"""
    ctx = toolset.make_context(task.input, task.meta, workdir)
    lower_bound = False
    for i, turn in enumerate(turns):
        text = turn["completion"]["text"]
        ctx.data["last_text"] = text
        try:
            outcome = toolset.parse(text)
        except ToolParseError:
            continue  # parse 失败在真实运行中只是 feedback，磁带继续
        if isinstance(outcome, Done):
            break
        for call in outcome:
            try:
                toolset.invoke(call, ctx)
            except Exception:
                if i + 1 >= len(turns):
                    # 磁带没有下一轮：真实运行本会多走一轮
                    lower_bound = True
                # 有下一轮 => 该失败只是 feedback，继续
    try:
        output = toolset.extract(ctx)
    except Exception:
        output = task.input
        lower_bound = True
    return output, lower_bound


def replay(out: Path, on_progress: Callable[[str], None] | None = None) -> dict:
    """对 out 下的运行做 replay；结果写入 report.json 的 replay 段。"""
    report_path = out / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    ds = report["dataset"]
    dataset = load_dataset(ds["dir"])
    tasks = {
        t.task_id: t
        for t in resolve(
            dataset,
            split=ds["split"],
            keys=ds.get("loader_keys"),
            meta=ds.get("meta"),
        )
    }

    changed: list[str] = []
    lower_bound: list[str] = []
    for name, cfg_dict in report["toolsets"].items():
        cfg = toolset_config_from_dict(name, cfg_dict)
        toolset = build_toolset(cfg)
        for task_id in report["per_sample"].get(name, {}):
            tape_path = out / "raw" / task_id / f"{name}.json"
            if not tape_path.is_file():
                continue
            tape = json.loads(tape_path.read_text(encoding="utf-8"))
            task = tasks[task_id]
            workdir = out / "replay-work" / task_id / name
            workdir.mkdir(parents=True, exist_ok=True)
            if not getattr(toolset, "uses_llm", True):
                continue  # noop 无后处理可重放
            output, lb = _replay_one(toolset, task, tape.get("turns", []), workdir)
            key = f"{task_id} × {name}"
            if lb:
                lower_bound.append(key)
            if output != tape.get("output", task.input):
                changed.append(key)
                # 更新磁带输出（后处理变了 => 结果变），原始 turns 不动
                tape["output"] = output
                if lb:
                    tape["status"] = "failed"
                tmp = tape_path.with_suffix(".tmp")
                tmp.write_text(
                    json.dumps(tape, ensure_ascii=False, indent=1), encoding="utf-8"
                )
                os.replace(tmp, tape_path)
            if on_progress:
                on_progress(f"replay: {key}")

    report["replay"] = {"changed": changed, "lower_bound": lower_bound}
    tmp = report_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, report_path)
    return report["replay"]
