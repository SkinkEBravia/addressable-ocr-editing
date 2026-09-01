"""replay：确定性后处理变更后的磁带重放（不调 LLM）。

对应 Docs/Design/08-eval-framework.md「重放（replay）」节：当改动只涉及
确定性后处理（degrade / apply / reconstruct / JSON 提取）而不涉及 prompt
时，用 ``out_dir/raw/<sample>/<arm>.json`` 里已存的磁带重算 corrected_text
与 report。

规则实现：

- 样本从 ``--data`` + ``--track`` 重建（尊重 ``--limit``）；臂配置从
  ``report.json`` 的 ``arms.<name>.config`` 读回（即当时运行的配置），
  不使用当前 ``configs/arms/`` 里的同名文件。
- 按磁带轮序对每轮已存 response 重跑后处理（与 runner 共用
  ``arms.try_extract`` / ``arms.try_apply``）；首个成功轮即结果；
  token 计数沿用磁带。
- 若新代码下所有已存轮都失败（真实运行本会发起新的 LLM 重试），按
  failed 回退原文——此时 replay 是真实重跑的下界，记入
  ``ReplayResult.lower_bound``，由 CLI 写入 report 并打印。
- raw 磁带文件本身不动。

与 08 文档的一处偏差（此处注明）：旧版 report.json 没有 ``arms`` 键时
（TOML 配置系统之前产生的运行），回退到 ``configs/arms/<name>.toml``
并在 ``config_warnings`` 中注明；该回退只对当时就是默认配置的臂是安全的。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import surface
from sourceio import SourceText

from experiment_app.arm_config import (
    DEFAULT_ARMS_DIR,
    ArmConfig,
    arm_config_from_dict,
    load_arm_config,
)
from experiment_app.arms import build_store, try_apply, try_extract
from experiment_app.datasets import DOC_SEPARATOR, Sample
from experiment_app.run import RunRecord, SampleArmRecord, _safe_id

__all__ = ["ReplayChange", "ReplayResult", "replay_experiment"]


@dataclass(frozen=True)
class ReplayChange:
    """一次重放导致的 outcome 变化（corrected_text 或 failed 与磁带不同）。"""

    sample_id: str
    arm: str
    old_text: str
    new_text: str
    old_failed: bool
    new_failed: bool


@dataclass(frozen=True)
class ReplayResult:
    """重放结果：可直接喂给 report.build_report，外加变化摘要。"""

    run_record: RunRecord
    arm_configs: dict[str, ArmConfig]
    model: str | None
    changes: tuple[ReplayChange, ...]
    lower_bound: tuple[tuple[str, str], ...]
    """(sample_id, arm)：磁带成功但重放失败 -> 按 failed 回退原文（下界情形）。"""
    config_warnings: tuple[str, ...]


def _load_tape_configs(
    old_report: dict, out_dir: Path
) -> tuple[dict[str, ArmConfig], list[str]]:
    """臂配置优先从 report.json 的 arms.<name>.config 读回；缺失时回退默认 TOML。"""
    configs: dict[str, ArmConfig] = {}
    warnings: list[str] = []

    for name, entry in old_report.get("arms", {}).items():
        configs[name] = arm_config_from_dict(entry["config"])

    # raw 目录里存在但 report 没有配置的臂：回退 configs/arms/（旧版运行）
    raw_root = out_dir / "raw"
    tape_arms: set[str] = set()
    if raw_root.is_dir():
        for sample_dir in raw_root.iterdir():
            if sample_dir.is_dir():
                tape_arms.update(p.stem for p in sample_dir.glob("*.json"))
    for name in sorted(tape_arms - set(configs)):
        fallback = DEFAULT_ARMS_DIR / f"{name}.toml"
        if fallback.is_file():
            configs[name] = load_arm_config(name, fallback)
            warnings.append(
                f"臂 {name!r} 的配置不在旧 report.json 中，回退到 {fallback}（仅当当时即默认配置时安全）"
            )
        else:
            warnings.append(f"臂 {name!r} 无配置来源（report.json 与 configs/arms/ 均无），跳过")
    return configs, warnings


def _replay_rounds_rewrite(sample: Sample, tape: dict) -> tuple[str, bool]:
    """rewrite 通道重放：首个能解析出 ocr_postcorrection_output 的轮次即结果。"""
    for entry in tape["raw"]:
        try:
            return try_extract(entry["response"]), False
        except ValueError:
            continue
    return sample.ocr_text, True


def _replay_rounds_patch(
    sample: Sample, config: ArmConfig, tape: dict, workdir: Path
) -> tuple[str, bool]:
    """patch 通道重放：重建快照，首个能 run_patch 成功的轮次即结果。"""
    source = SourceText(text=sample.ocr_text, encoding="utf-8", bom=b"")
    store = build_store(workdir, source, config)
    for entry in tape["raw"]:
        try:
            return try_apply(store, entry["response"]), False
        except (surface.ParseError, surface.SurfaceError):
            continue
    return sample.ocr_text, True


def _replay_rounds_pieces(sample: Sample, tape: dict) -> tuple[str, bool]:
    """rewrite_pieces 通道重放：按 unit_index 分单元，逐单元取首个成功轮。"""
    by_unit: dict[int, list[dict]] = {}
    for entry in tape["raw"]:
        by_unit.setdefault(entry.get("unit_index", 0), []).append(entry)
    parts: list[str] = []
    any_failed = False
    for index, unit in enumerate(sample.split_units()):
        text, failed = unit, True
        for entry in by_unit.get(index, []):
            try:
                text, failed = try_extract(entry["response"]), False
                break
            except ValueError:
                continue
        parts.append(text)
        any_failed = any_failed or failed
    return DOC_SEPARATOR.join(parts), any_failed


def _replay_one(
    sample: Sample, config: ArmConfig, tape: dict, workdir: Path
) -> tuple[str, bool]:
    """对单个 (sample, arm) 磁带重放，返回 (corrected_text, failed)。"""
    match config.channel:
        case "noop":
            return sample.ocr_text, False
        case "rewrite":
            return _replay_rounds_rewrite(sample, tape)
        case "patch":
            return _replay_rounds_patch(sample, config, tape, workdir)
        case "rewrite_pieces":
            return _replay_rounds_pieces(sample, tape)
    raise ValueError(f"unknown channel: {config.channel!r}")


def replay_experiment(samples: tuple[Sample, ...], out_dir: Path) -> ReplayResult:
    """重放一次既有运行：重算 corrected_text、重写 results.jsonl（report 由调用方写）。

    只处理磁带存在的 (sample, arm)；raw 文件不动；token 沿用磁带。
    """
    out_dir = Path(out_dir)
    old_report_path = out_dir / "report.json"
    old_report: dict = {}
    if old_report_path.is_file():
        old_report = json.loads(old_report_path.read_text(encoding="utf-8"))
    model = old_report.get("model")

    arm_configs, config_warnings = _load_tape_configs(old_report, out_dir)

    records: list[SampleArmRecord] = []
    changes: list[ReplayChange] = []
    lower_bound: list[tuple[str, str]] = []
    for sample in samples:
        for arm_name, config in arm_configs.items():
            raw_path = out_dir / "raw" / _safe_id(sample.sample_id) / f"{arm_name}.json"
            if not raw_path.is_file():
                continue
            tape = json.loads(raw_path.read_text(encoding="utf-8"))
            workdir = out_dir / "sessions" / _safe_id(sample.sample_id) / arm_name
            corrected, failed = _replay_one(sample, config, tape, workdir)

            old_text = tape.get("corrected_text", "")
            old_failed = bool(tape.get("failed", False))
            if corrected != old_text or failed != old_failed:
                changes.append(
                    ReplayChange(
                        sample_id=sample.sample_id,
                        arm=arm_name,
                        old_text=old_text,
                        new_text=corrected,
                        old_failed=old_failed,
                        new_failed=failed,
                    )
                )
            if failed and not old_failed:
                lower_bound.append((sample.sample_id, arm_name))

            records.append(
                SampleArmRecord(
                    sample_id=sample.sample_id,
                    track=sample.track,
                    language=sample.language,
                    source_subset=sample.source_subset,
                    arm=arm_name,
                    corrected_text=corrected,
                    tokens_in=tape["tokens_in"],
                    tokens_out=tape["tokens_out"],
                    tokens_total=tape["tokens_in"] + tape["tokens_out"],
                    rounds=tape["rounds"],
                    failed=failed,
                )
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    track = samples[0].track if samples else "unit"
    run_record = RunRecord(track=track, samples=tuple(samples), records=tuple(records))
    return ReplayResult(
        run_record=run_record,
        arm_configs=arm_configs,
        model=model,
        changes=tuple(changes),
        lower_bound=tuple(lower_bound),
        config_warnings=tuple(config_warnings),
    )
