"""run：执行矩阵 + 原始记录落盘 + CLI 入口。

对应 Docs/Design/08-eval-framework.md「架构」「臂配置（TOML）」「验收」节。

- 臂由 TOML 配置驱动：``--arms a,b`` 解析为 ``configs/arms/<name>.toml``；
  ``--arm-config 标签=路径`` 可重复，标签成为报告里的臂名（同通道两变体
  可同跑，如 sys_v1 / sys_v2）。
- 每臂独立 client：temperature 是臂级配置，``client_factory`` 签名
  ``factory(model, *, temperature=...)``；``--model fake`` 用内置
  FakeClient（确定性响应，离线冒烟），其他模型名默认 DeepSeekClient。
- ``run_experiment``：逐样本 × 逐臂并发执行（ThreadPoolExecutor）；每样本
  每臂的原始记录（prompt/response/usage）落盘到
  ``out_dir/raw/{sample_id}/{arm}.json``，已存在则跳过（断点续跑）；
  汇总写 ``out_dir/results.jsonl``。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

from llm import Completion, DeepSeekClient, LLMClient, Usage

from experiment_app.arm_config import (
    DEFAULT_ARMS_DIR,
    ArmConfig,
    build_arm,
    load_arm_config,
)
from experiment_app.arms import Arm, ArmResult
from experiment_app.datasets import Sample, load_samples

__all__ = [
    "Arm",
    "DEFAULT_ARM_NAMES",
    "SampleArmRecord",
    "RunRecord",
    "FakeClient",
    "ClientFactory",
    "default_client_factory",
    "load_cli_arm_configs",
    "run_experiment",
    "main",
]

DEFAULT_ARM_NAMES = ("noop", "blocr", "blocr_system", "ref_blocr_pieces")
"""默认臂：``configs/arms/`` 下的四个 TOML。"""

ClientFactory = Callable[..., LLMClient]
"""client 工厂签名：``factory(model, *, temperature=...) -> LLMClient``。"""


@dataclass(frozen=True)
class SampleArmRecord:
    """单样本单臂的汇总记录（原始 prompt/response 落盘于 raw/）。"""

    sample_id: str
    track: str
    language: str
    source_subset: str
    arm: str
    corrected_text: str
    tokens_in: int
    tokens_out: int
    tokens_total: int
    rounds: int
    failed: bool


@dataclass(frozen=True)
class RunRecord:
    """一次实验的完整记录：样本 + 逐样本逐臂结果。"""

    track: str
    samples: tuple[Sample, ...]
    records: tuple[SampleArmRecord, ...]


class FakeClient:
    """确定性假客户端，供离线冒烟与测试。

    - patch 臂（prompt 含 ``--- OCR VIEW`` 标记）：返回空 patch（无改动）。
    - rewrite 臂（prompt 含 ``--- OCR TEXT`` 标记）：返回原文的 JSON。
    usage 为确定性的本地计数（仅 fake 通道，真实臂以 API usage 为准）。
    """

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, system: str | None = None) -> Completion:
        self.prompts.append(prompt)
        if "--- OCR VIEW" in prompt:
            text = ""
        else:
            text = json.dumps(
                {"ocr_postcorrection_output": _extract_marked_text(prompt)},
                ensure_ascii=False,
            )
        return Completion(
            text=text,
            usage=Usage(
                input_tokens=max(1, len(prompt) // 4),
                output_tokens=max(1, len(text) // 4),
            ),
        )


def _extract_marked_text(prompt: str) -> str:
    """从 rewrite 模板渲染的 prompt 中提取 --- OCR TEXT 标记段内的原文。"""
    match = re.search(
        r"--- OCR TEXT \(language: [^\n]*\) ---\n(.*?)\n--- END OF OCR TEXT ---",
        prompt,
        re.DOTALL,
    )
    return match.group(1) if match else ""


def default_client_factory(model: str, *, temperature: float = 0.2) -> LLMClient:
    """默认 client 工厂：``fake`` -> FakeClient，其他 -> DeepSeekClient。"""
    if model == "fake":
        return FakeClient()
    return DeepSeekClient(model=model, temperature=temperature)


_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_id(sample_id: str) -> str:
    """sample_id -> 路径安全的目录名。"""
    return _SAFE_ID.sub("_", sample_id)


def _run_one(
    sample: Sample, arm_name: str, arm_fn: Arm, client: LLMClient, out_dir: Path
) -> SampleArmRecord:
    """执行单个 (sample, arm)；raw json 已存在则跳过执行直接读取（断点续跑）。"""
    raw_path = out_dir / "raw" / _safe_id(sample.sample_id) / f"{arm_name}.json"

    if raw_path.exists():
        saved = json.loads(raw_path.read_text(encoding="utf-8"))
        return SampleArmRecord(
            sample_id=sample.sample_id,
            track=sample.track,
            language=sample.language,
            source_subset=sample.source_subset,
            arm=arm_name,
            corrected_text=saved["corrected_text"],
            tokens_in=saved["tokens_in"],
            tokens_out=saved["tokens_out"],
            tokens_total=saved["tokens_in"] + saved["tokens_out"],
            rounds=saved["rounds"],
            failed=saved["failed"],
        )

    workdir = out_dir / "sessions" / _safe_id(sample.sample_id) / arm_name
    workdir.mkdir(parents=True, exist_ok=True)
    result = arm_fn(sample, client, workdir)

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        json.dumps(
            {
                "sample_id": sample.sample_id,
                "arm": arm_name,
                "rounds": result.rounds,
                "failed": result.failed,
                "corrected_text": result.corrected_text,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
                "raw": list(result.raw),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return SampleArmRecord(
        sample_id=sample.sample_id,
        track=sample.track,
        language=sample.language,
        source_subset=sample.source_subset,
        arm=arm_name,
        corrected_text=result.corrected_text,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        tokens_total=result.tokens_in + result.tokens_out,
        rounds=result.rounds,
        failed=result.failed,
    )


def run_experiment(
    samples: tuple[Sample, ...],
    arms: dict[str, Arm],
    clients: dict[str, LLMClient],
    out_dir: Path,
    workers: int = 8,
) -> RunRecord:
    """逐样本 × 逐臂并发执行，落盘原始记录与汇总 jsonl，返回 RunRecord。

    - ``arms`` 与 ``clients`` 同键（臂名）；每臂用独立 client
      （temperature 是臂级配置）。
    - ``workers`` 控制并发度（API 可并发）；每个 (sample, arm) 有独立
      workdir 与 raw 文件，天然线程安全。
    - 断点续跑：raw json 已存在的 (sample, arm) 跳过执行，直接读汇总字段。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = [(s, name, fn) for s in samples for name, fn in arms.items()]
    done: dict[tuple[str, str], SampleArmRecord] = {}
    total = len(tasks)
    completed = 0

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(_run_one, s, name, fn, clients[name], out_dir): (
                s.sample_id,
                name,
            )
            for s, name, fn in tasks
        }
        for future in as_completed(futures):
            record = future.result()
            done[(record.sample_id, record.arm)] = record
            completed += 1
            print(
                f"[{completed}/{total}] {record.sample_id} {record.arm} "
                f"tokens={record.tokens_total} failed={record.failed}",
                file=sys.stderr,
            )

    # 汇总按 (样本序 × 臂序) 确定性排序，保证复现
    order = {
        (s.sample_id, name): i
        for i, (s, name, _) in enumerate(tasks)
    }
    records = sorted(done.values(), key=lambda r: order[(r.sample_id, r.arm)])

    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    track = samples[0].track if samples else "unit"
    return RunRecord(track=track, samples=tuple(samples), records=tuple(records))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="experiment_app",
        description="HIPE-OCRepair 测评：blocr（完全重写）vs blocr+system（块补丁）",
    )
    parser.add_argument(
        "--data",
        action="append",
        required=True,
        metavar="JSONL",
        help="输入 jsonl 路径，可多次指定",
    )
    parser.add_argument("--track", choices=["unit", "doc"], required=True)
    parser.add_argument(
        "--arms",
        default=",".join(DEFAULT_ARM_NAMES),
        help="逗号分隔的臂名，解析为 configs/arms/<name>.toml（默认四个默认臂）",
    )
    parser.add_argument(
        "--arm-config",
        action="append",
        default=[],
        metavar="标签=路径",
        help="自定义臂配置（可重复）；标签成为报告里的臂名",
    )
    parser.add_argument("--limit", type=int, default=None, metavar="N")
    parser.add_argument("--out", required=True, metavar="DIR")
    parser.add_argument("--model", default="fake", help="模型名；fake = 离线确定性假客户端")
    parser.add_argument(
        "--workers", type=int, default=8, metavar="N", help="并发度（默认 8）"
    )
    return parser.parse_args(argv)


def load_cli_arm_configs(arms: str, arm_config_specs: list[str]) -> dict[str, ArmConfig]:
    """CLI 参数 -> {臂名: ArmConfig}。

    - ``--arms a,b`` -> ``configs/arms/<name>.toml``；文件不存在报清晰错误。
    - ``--arm-config 标签=路径``：标签成为报告里的臂名；与 --arms 重名报错。
    """
    configs: dict[str, ArmConfig] = {}
    for name in arms.split(","):
        name = name.strip()
        path = DEFAULT_ARMS_DIR / f"{name}.toml"
        if not path.is_file():
            raise SystemExit(
                f"arm 配置不存在: {path}（--arms {name!r}；"
                f"自定义配置请用 --arm-config 标签=路径）"
            )
        configs[name] = load_arm_config(name, path)
    for spec in arm_config_specs:
        label, sep, path_text = spec.partition("=")
        if not sep or not label.strip() or not path_text.strip():
            raise SystemExit(f"--arm-config 需要 '标签=路径' 形式，got {spec!r}")
        label = label.strip()
        if label in configs:
            raise SystemExit(f"臂名重复: {label!r}（--arms 与 --arm-config 冲突）")
        path = Path(path_text.strip())
        if not path.is_file():
            raise SystemExit(f"arm 配置不存在: {path}（--arm-config {spec!r}）")
        configs[label] = load_arm_config(label, path)
    return configs


def main(argv: list[str] | None = None, *, client_factory: ClientFactory | None = None) -> int:
    """CLI 入口。``client_factory`` 供测试注入假 client。"""
    args = _parse_args(argv)

    samples: list[Sample] = []
    for data_path in args.data:
        samples.extend(load_samples(Path(data_path), args.track))
    if args.limit is not None:
        samples = samples[: args.limit]
    if not samples:
        raise SystemExit("no samples loaded")

    arm_configs = load_cli_arm_configs(args.arms, args.arm_config)
    arms = {name: build_arm(config) for name, config in arm_configs.items()}

    factory = client_factory or default_client_factory
    clients = {
        name: factory(args.model, temperature=config.temperature)
        for name, config in arm_configs.items()
    }

    run_record = run_experiment(
        tuple(samples), arms, clients, Path(args.out), workers=args.workers
    )

    from experiment_app.report import build_report, render_markdown

    report = build_report(run_record, model=args.model, arm_configs=arm_configs)
    report_path = Path(args.out) / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(render_markdown(report))
    print(f"\nreport written to {report_path}")
    return 0
