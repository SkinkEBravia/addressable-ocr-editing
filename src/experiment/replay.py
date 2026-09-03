"""experiment 的 replay：改动只涉确定性后处理时免重跑 LLM。

对应 Docs/Design/11-experiment.md「replay」节。

- 按磁带逐轮重放后处理（parse / invoke / extract），token 沿用记录值。
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

from agent import (
    Done,
    Session,
    ToolParseError,
    build_toolset,
    load_toolset_config,
    toolset_config_from_dict,
)
from datasetkit import load_dataset, resolve

from experiment.store import SessionStore

__all__ = ["replay"]


def _replay_one(
    toolset: Any, task: Any, session: Session, workdir: Path
) -> tuple[str, bool]:
    """重放一个 (task, toolset)：重 fold 磁带里的 calls。返回 (output, lower_bound)。"""
    tool_state = toolset.make_tool_state(task.input, task.meta, workdir)
    lower_bound = False
    for i, turn in enumerate(session.turns):
        text = turn.completion.text
        try:
            outcome = toolset.parse(text)
        except ToolParseError:
            continue  # parse 失败在真实运行中只是 feedback，磁带继续
        if isinstance(outcome, Done):
            break
        for call in outcome:
            try:
                toolset.invoke(call, tool_state)
            except Exception:
                if i + 1 >= len(session.turns):
                    # 磁带没有下一轮：真实运行本会多走一轮
                    lower_bound = True
                # 有下一轮 => 该失败只是 feedback，继续
    try:
        output = toolset.extract(tool_state, session).text
    except Exception:
        output = task.input
        lower_bound = True
    return output, lower_bound


def replay(
    out: Path,
    on_progress: Callable[[str], None] | None = None,
    toolset_overrides: dict[str, str] | None = None,
) -> dict:
    """对 out 下的运行做 replay；结果写入 report.json 的 replay 段。

    toolset_overrides：磁带标签 -> 工具配置名（configs/toolsets/<名>.toml）。
    只替换重 fold 用的工具集行为（如 apply 策略）——fold 是确定性后处理，
    不换 prompt/模型即不违反 replay 口径；覆盖关系记入报告。
    """
    out = Path(out)
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
    store = SessionStore(out)

    changed: list[str] = []
    lower_bound: list[str] = []
    for name, cfg_dict in report["toolsets"].items():
        if toolset_overrides and name in toolset_overrides:
            cfg = load_toolset_config(toolset_overrides[name])
        else:
            cfg = toolset_config_from_dict(name, cfg_dict)
        toolset = build_toolset(cfg)
        if not getattr(toolset, "uses_llm", True):
            continue  # noop 无后处理可重放
        for task_id in report["per_sample"].get(name, {}):
            session = store.read(task_id, name)
            if session is None:
                continue
            task = tasks[task_id]
            workdir = out / "replay-work" / task_id / name
            workdir.mkdir(parents=True, exist_ok=True)
            output, lb = _replay_one(toolset, task, session, workdir)
            key = f"{task_id} × {name}"
            if lb:
                lower_bound.append(key)
            old_output = session.output if session.output is not None else task.input
            if output != old_output:
                changed.append(key)
                # 后处理变了 => 结果变；更新磁带 output，原始 turns 不动
                session.output = output
                if lb:
                    session.status = "failed"
                store.write(session)
            if on_progress:
                on_progress(f"replay: {key}")

    result: dict = {"changed": changed, "lower_bound": lower_bound}
    if toolset_overrides:
        result["toolset_overrides"] = dict(toolset_overrides)
    report["replay"] = result
    tmp = report_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, report_path)
    return report["replay"]
