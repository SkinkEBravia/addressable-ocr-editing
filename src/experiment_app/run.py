"""run：执行矩阵 + 原始记录落盘 + CLI 入口。

对应 Docs/Design/08-eval-framework.md「架构」「验收」节。

- ``run_experiment``：逐样本 × 逐臂执行；每样本每臂的原始记录
  （prompt/response/usage）落盘到 ``out_dir/raw/{sample_id}/{arm}.json``；
  汇总写 ``out_dir/results.jsonl``。
- ``main``：CLI；``--model fake`` 用内置 FakeClient（确定性响应，离线冒烟），
  其他模型名默认 DeepSeekClient。依赖注入：``main(argv, client_factory=...)``。
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

from experiment_app.arms import (
    ArmResult,
    arm_blocr,
    arm_blocr_system,
    arm_noop,
    arm_ref_blocr_pieces,
)
from experiment_app.datasets import Sample, load_samples

__all__ = [
    "Arm",
    "ARMS",
    "SampleArmRecord",
    "RunRecord",
    "FakeClient",
    "default_client_factory",
    "run_experiment",
    "main",
]

Arm = Callable[[Sample, LLMClient, Path], ArmResult]
"""臂签名：(sample, client, workdir) -> ArmResult。"""

ARMS: dict[str, Arm] = {
    "noop": arm_noop,
    "blocr": arm_blocr,
    "blocr_system": arm_blocr_system,
    "ref_blocr_pieces": arm_ref_blocr_pieces,
}
"""可用臂注册表（CLI --arms 的名字空间）。"""

ClientFactory = Callable[[str], LLMClient]


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


def default_client_factory(model: str) -> LLMClient:
    """默认 client 工厂：``fake`` -> FakeClient，其他 -> DeepSeekClient。"""
    if model == "fake":
        return FakeClient()
    return DeepSeekClient(model=model)


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
    client: LLMClient,
    out_dir: Path,
    workers: int = 8,
) -> RunRecord:
    """逐样本 × 逐臂并发执行，落盘原始记录与汇总 jsonl，返回 RunRecord。

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
            pool.submit(_run_one, s, name, fn, client, out_dir): (s.sample_id, name)
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
        default=",".join(ARMS),
        help=f"逗号分隔的臂名，可选：{', '.join(ARMS)}（默认全部）",
    )
    parser.add_argument("--limit", type=int, default=None, metavar="N")
    parser.add_argument("--out", required=True, metavar="DIR")
    parser.add_argument("--model", default="fake", help="模型名；fake = 离线确定性假客户端")
    parser.add_argument(
        "--workers", type=int, default=8, metavar="N", help="并发度（默认 8）"
    )
    return parser.parse_args(argv)


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

    selected: dict[str, Arm] = {}
    for name in args.arms.split(","):
        name = name.strip()
        if name not in ARMS:
            raise SystemExit(f"unknown arm: {name!r} (available: {', '.join(ARMS)})")
        selected[name] = ARMS[name]

    factory = client_factory or default_client_factory
    client = factory(args.model)

    run_record = run_experiment(
        tuple(samples), selected, client, Path(args.out), workers=args.workers
    )

    from experiment_app.report import build_report, render_markdown

    report = build_report(run_record, model=args.model)
    report_path = Path(args.out) / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(render_markdown(report))
    print(f"\nreport written to {report_path}")
    return 0
