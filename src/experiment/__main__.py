"""experiment 的 CLI（python -m experiment）。

对应 Docs/Design/11-experiment.md「运行配置」节。

    python -m experiment --dataset <dir> --toolsets a,b --model m \
        --split dev [--loaders icdar2017/en/doc,dta19-l0/de/chunk] \
        [--ids-from meta:key=value] [--ids ...] [--limit N] \
        [--instruction <路径>] [--no-stream] [--workers N] --out runs/<name>
    python -m experiment --out runs/<name> --replay
    python -m experiment --out runs/<name> --report-only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent import load_toolset_config
from llm import build_client, load_model_config

from experiment.progress import build_reporter
from experiment.replay import replay
from experiment.report import build_report, write_report
from experiment.run import run_experiment


def _split_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _parse_ids_from(pairs: list[str] | None) -> dict[str, str] | None:
    """--ids-from meta:key=value（可重复，AND）→ meta 等值过滤 dict。"""
    if not pairs:
        return None
    meta: dict[str, str] = {}
    for pair in pairs:
        prefix, sep, rest = pair.partition(":")
        key, eq, value = rest.partition("=")
        if prefix != "meta" or not sep or not eq or not key.strip():
            raise SystemExit(f"error: --ids-from 需要 meta:key=value 形式，got {pair!r}")
        meta[key.strip()] = value.strip()
    return meta


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="experiment",
        description="实验装配：dataset × toolset × model 的执行矩阵（11-experiment.md）。",
    )
    p.add_argument("--dataset", help="含 dataset.py 的目录")
    p.add_argument("--toolsets", help="工具配置名，逗号分隔（configs/toolsets/<name>.toml）")
    p.add_argument("--model", help="模型配置名（configs/models/<name>.toml）；同一实验单一模型")
    p.add_argument("--split", help="数据集 split（如 dev / train / test）")
    p.add_argument(
        "--loaders",
        default=None,
        help="loader key 列表，逗号分隔（如 icdar2017/en/doc）；缺省 = 该 split 全部 loader 串联",
    )
    p.add_argument(
        "--ids-from",
        action="append",
        default=None,
        help="meta 等值过滤：meta:key=value，可重复（AND）；如 meta:document=periodical__eng_periodical-3",
    )
    p.add_argument("--ids", default=None, help="task_id 列表，逗号分隔")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--instruction", default=None, help="instruction 模板路径（覆盖数据集默认）")
    p.add_argument("--out", required=True, help="输出目录 runs/<name>")
    p.add_argument("--workers", type=int, default=1, help="并发路数（默认 1 串行）")
    p.add_argument(
        "--no-stream",
        action="store_true",
        help="关流式请求（默认开）；只影响观察通道，不改变语义与落盘",
    )
    p.add_argument(
        "--reporter",
        default=None,
        help="运行时报告器：rich（默认，流式 TPS）/ null / module:Class（自研组件入口）",
    )
    p.add_argument("--replay", action="store_true", help="磁带重放后处理（不重打 API）")
    p.add_argument(
        "--replay-with",
        action="append",
        default=None,
        metavar="LABEL=CONFIG",
        help="replay 时替换某工具配置标签的 fold 行为（如 patch-1turn=patch-1turn-lenient）；可重复",
    )
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
        overrides = None
        if args.replay_with:
            overrides = {}
            for pair in args.replay_with:
                label, sep, cfg_name = pair.partition("=")
                if not sep or not label.strip() or not cfg_name.strip():
                    print(f"error: --replay-with 需要 LABEL=CONFIG 形式，got {pair!r}",
                          file=sys.stderr)
                    return 2
                overrides[label.strip()] = cfg_name.strip()
        result = replay(out, on_progress=progress, toolset_overrides=overrides)
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
    prog = build_reporter(args.reporter)
    try:
        summary = run_experiment(
            dataset_dir=Path(args.dataset),
            toolset_configs=toolset_configs,
            client=client,
            model_config_dict=model_config.as_dict(),
            split=args.split,
            loader_keys=_split_csv(args.loaders),
            meta_filter=_parse_ids_from(args.ids_from),
            ids=_split_csv(args.ids),
            limit=args.limit,
            instruction=instruction,
            out=out,
            workers=args.workers,
            stream=not args.no_stream,
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
        from experiment.report import resolve_dataset_dir

        dataset_dir = resolve_dataset_dir(old["dataset"]["dir"])
        split = old["dataset"]["split"]
        loader_keys = old["dataset"].get("loader_keys")
        meta_filter = old["dataset"].get("meta")
        names = list(toolsets)
        instruction_src = None
    else:
        models = {model_config.name: model_config.as_dict()}
        toolsets = {c.name: c.as_dict() for c in toolset_configs}
        dataset_dir = args.dataset
        split = args.split
        loader_keys = _split_csv(args.loaders)
        meta_filter = _parse_ids_from(args.ids_from)
        names = [c.name for c in toolset_configs]
        instruction_src = instruction
    report = build_report(
        dataset_dir=Path(dataset_dir),
        split=split,
        loader_keys=loader_keys,
        meta=meta_filter,
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
