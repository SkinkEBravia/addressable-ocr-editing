"""experiment 的 CLI（python -m experiment）。

对应 Docs/Design/11-experiment.md「运行配置」节。

    python -m experiment --dataset <dir> --toolsets a,b --model m \
        --split dev [--granularity doc] [--ids ...] [--languages de,en] \
        [--limit N] [--instruction <路径>] --out runs/<name>
    python -m experiment --out runs/<name> --replay
    python -m experiment --out runs/<name> --report-only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from llm import build_client, load_model_config

from experiment.config import load_toolset_config
from experiment.replay import replay
from experiment.report import build_report, write_report
from experiment.run import run_experiment


def _split_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="experiment",
        description="实验装配：dataset × toolset × model 的执行矩阵（11-experiment.md）。",
    )
    p.add_argument("--dataset", help="含 dataset.py 的目录")
    p.add_argument("--toolsets", help="工具配置名，逗号分隔（configs/toolsets/<name>.toml）")
    p.add_argument("--model", help="模型配置名（configs/models/<name>.toml）；同一实验单一模型")
    p.add_argument("--split", help="数据集 split（如 dev / train / test）")
    p.add_argument("--granularity", default=None, help="任务粒度（数据集自定，如 unit / doc）")
    p.add_argument("--ids", default=None, help="task_id 列表，逗号分隔")
    p.add_argument("--languages", default=None, help="语言过滤，逗号分隔")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--instruction", default=None, help="instruction 模板路径（覆盖数据集默认）")
    p.add_argument("--out", required=True, help="输出目录 runs/<name>")
    p.add_argument("--workers", type=int, default=1, help="并发路数（默认 1 串行）")
    p.add_argument(
        "--reporter",
        default=None,
        help="运行时报告器：rich（默认）/ null / module:Class（自研组件入口）",
    )
    p.add_argument("--replay", action="store_true", help="磁带重放后处理（不重打 API）")
    p.add_argument("--report-only", action="store_true", help="只重建报告（不重跑）")
    return p


def main(argv: list[str] | None = None) -> int:
    from llm import load_env_file

    load_env_file()  # 项目 .env 先进进程环境，再解析任何凭证
    args = _build_parser().parse_args(argv)
    out = Path(args.out)

    def progress(msg: str) -> None:
        print(msg, file=sys.stderr)

    if args.replay:
        result = replay(out, on_progress=progress)
        print(f"replay: changed={len(result['changed'])} lower_bound={len(result['lower_bound'])}")
        return 0

    if args.report_only:
        _emit_report(args, out)
        return 0

    for required in ("dataset", "toolsets", "model", "split"):
        if getattr(args, required) is None:
            print(f"error: --{required} 必需", file=sys.stderr)
            return 2

    model_config = load_model_config(args.model)
    toolset_configs = [load_toolset_config(n) for n in _split_csv(args.toolsets) or []]
    instruction = None
    if args.instruction:
        instruction = Path(args.instruction).read_text(encoding="utf-8")

    client = build_client(model_config)
    from experiment.progress import build_reporter

    prog = build_reporter(args.reporter)
    try:
        summary = run_experiment(
            dataset_dir=Path(args.dataset),
            toolset_configs=toolset_configs,
            client=client,
            model_config_dict=model_config.as_dict(),
            split=args.split,
            granularity=args.granularity,
            ids=_split_csv(args.ids),
            languages=_split_csv(args.languages),
            limit=args.limit,
            instruction=instruction,
            out=out,
            workers=args.workers,
            progress=prog,
        )
    finally:
        prog.close()  # 停掉 Live 刷新块（transient：清屏不堆历史）
    _emit_report(args, out, model_config, toolset_configs, instruction)
    counts: dict[str, int] = {}
    for status in summary.values():
        counts[status] = counts.get(status, 0) + 1
    print(f"done: {counts}")
    return 0


def _emit_report(args, out: Path, model_config=None, toolset_configs=None, instruction=None) -> None:
    if model_config is None or toolset_configs is None:
        # report-only：从现有 report.json 读配置
        import json

        old = json.loads((out / "report.json").read_text(encoding="utf-8"))
        models = old["models"]
        toolsets = old["toolsets"]
        dataset_dir = old["dataset"]["dir"]
        split = old["dataset"]["split"]
        granularity = old["dataset"]["granularity"]
        names = list(toolsets)
        instruction_src = None
    else:
        models = {model_config.name: model_config.as_dict()}
        toolsets = {c.name: c.as_dict() for c in toolset_configs}
        dataset_dir = args.dataset
        split = args.split
        granularity = args.granularity
        names = [c.name for c in toolset_configs]
        instruction_src = instruction
    report = build_report(
        dataset_dir=Path(dataset_dir),
        split=split,
        granularity=granularity,
        out=out,
        toolset_names=names,
        model_config_dicts=models,
        toolset_config_dicts=toolsets,
        instruction=instruction_src,
    )
    if model_config is None and "replay" in old:
        report["replay"] = old["replay"]  # 报告重建不丢 replay 段
    path = write_report(report, out)
    print(f"report: {path}")


if __name__ == "__main__":
    raise SystemExit(main())
