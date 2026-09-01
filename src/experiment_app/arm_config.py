"""arm_config：臂配置（TOML）的解析、校验与装配。

对应 Docs/Design/08-eval-framework.md「臂配置（TOML）」节：每个臂一个 TOML
文件，文件名即臂名，默认放在项目根 ``configs/arms/``。调提示词、改重试
预算、换块粒度都只改 TOML，不动代码。

与 08 文档接口的两处实现偏差（均在此注明）：

1. ``ArmConfig`` 多一个 ``prompt_base_dir`` 字段：prompt 的路径型引用按
   08 文档规则「相对 TOML 文件所在目录」解析，装配后的 Arm 不再持有 TOML
   路径，因此把 TOML 所在目录作为配置的一部分携带（包内模板名时为空串）。
2. report.json 的臂配置落盘：08 文档为 ``arms.<name>.config``；report.py
   现有结构是 groups 列表，实现为两者兼有——顶层 ``arms.<name>.config``
   （按文档）+ 每个 group 条目内的 ``config`` 字段（便于按行审计）。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from experiment_app.arms import (
    MAX_RETRIES,
    Arm,
    arm_noop,
    arm_patch,
    arm_rewrite,
    arm_rewrite_pieces,
)

__all__ = [
    "ArmConfig",
    "CHANNELS",
    "DEFAULT_ARMS_DIR",
    "load_arm_config",
    "arm_config_from_dict",
    "build_arm",
]

CHANNELS = ("noop", "rewrite", "patch", "rewrite_pieces")
"""合法 channel 值。"""

_PARTITIONS = ("lines", "chars")
"""patch 通道合法 partition 值。"""

DEFAULT_ARMS_DIR = Path(__file__).resolve().parents[2] / "configs" / "arms"
"""默认臂配置目录：项目根 configs/arms/（src/experiment_app/arm_config.py 上两级）。"""

_TOP_LEVEL_KEYS = ("channel", "prompt", "retries", "temperature", "patch")
_PATCH_KEYS = ("partition", "block_size")


@dataclass(frozen=True)
class ArmConfig:
    """一个臂的完整配置（TOML 解析结果，缺省键已填默认值）。"""

    name: str
    """报告标签（= 文件名或 --arm-config 的标签）。"""
    channel: str
    """执行通道：noop | rewrite | patch | rewrite_pieces。"""
    prompt: str = ""
    """模板名（包内 prompts/）或相对 TOML 文件的路径；noop 通道留空。"""
    retries: int = MAX_RETRIES
    """失败重试预算（总轮数 = 1 + retries）。"""
    temperature: float = 0.2
    """采样温度（臂级，client 按此构造）。"""
    partition: str = "lines"
    """patch 通道分区方式：lines | chars。"""
    block_size: int = 400
    """partition == "chars" 时的块大小。"""
    prompt_base_dir: str = ""
    """TOML 文件所在目录（prompt 路径型引用的解析基准；包内模板名时为空串）。"""


def _reject_unknown(data: dict, allowed: tuple[str, ...], where: str, path: Path) -> None:
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise ValueError(
            f"{path}: {where} 存在未知键 {unknown}（合法键：{list(allowed)}）"
        )


def load_arm_config(name: str, path: Path) -> ArmConfig:
    """解析 + 校验一个臂的 TOML 配置。

    - 未知顶层键 / 未知 ``[patch]`` 段键直接 ValueError（列出合法键，防拼写漂移）。
    - 缺省键取默认值；``channel`` 必填且合法；rewrite/patch/rewrite_pieces
      通道要求非空 ``prompt``。
    """
    path = Path(path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    _reject_unknown(data, _TOP_LEVEL_KEYS, "顶层", path)

    channel = data.get("channel")
    if channel not in CHANNELS:
        raise ValueError(f"{path}: channel 必须是 {list(CHANNELS)} 之一，got {channel!r}")

    prompt = data.get("prompt", "")
    if not isinstance(prompt, str):
        raise ValueError(f"{path}: prompt 必须是字符串，got {prompt!r}")
    if channel != "noop" and not prompt:
        raise ValueError(f"{path}: channel={channel!r} 要求非空 prompt")

    retries = data.get("retries", MAX_RETRIES)
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
        raise ValueError(f"{path}: retries 必须是非负整数，got {retries!r}")

    temperature = data.get("temperature", 0.2)
    if not isinstance(temperature, (int, float)) or isinstance(temperature, bool):
        raise ValueError(f"{path}: temperature 必须是数值，got {temperature!r}")

    patch = data.get("patch", {})
    if not isinstance(patch, dict):
        raise ValueError(f"{path}: [patch] 必须是表，got {patch!r}")
    _reject_unknown(patch, _PATCH_KEYS, "[patch] 段", path)

    partition = patch.get("partition", "lines")
    if partition not in _PARTITIONS:
        raise ValueError(f"{path}: [patch].partition 必须是 {list(_PARTITIONS)} 之一，got {partition!r}")
    block_size = patch.get("block_size", 400)
    if not isinstance(block_size, int) or isinstance(block_size, bool) or block_size < 1:
        raise ValueError(f"{path}: [patch].block_size 必须是正整数，got {block_size!r}")

    return ArmConfig(
        name=name,
        channel=channel,
        prompt=prompt,
        retries=retries,
        temperature=float(temperature),
        partition=partition,
        block_size=block_size,
        prompt_base_dir=str(path.parent),
    )


_CHANNELS: dict[str, object] = {
    "noop": arm_noop,
    "rewrite": arm_rewrite,
    "patch": arm_patch,
    "rewrite_pieces": arm_rewrite_pieces,
}


def arm_config_from_dict(data: dict) -> ArmConfig:
    """从 report.json 的 ``arms.<name>.config`` 字典重建 ArmConfig（replay 用）。

    与 TOML 解析同一套校验口径：未知键直接 ValueError（列出合法键），
    channel / partition 合法性同 ``load_arm_config``。字典为扁平结构
    （partition / block_size 在顶层），缺省键取默认值。
    """
    allowed = tuple(ArmConfig.__dataclass_fields__)
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise ValueError(f"臂配置字典存在未知键 {unknown}（合法键：{list(allowed)}）")
    config = ArmConfig(**{k: v for k, v in data.items() if k in allowed})
    if config.channel not in CHANNELS:
        raise ValueError(f"channel 必须是 {list(CHANNELS)} 之一，got {config.channel!r}")
    if config.partition not in _PARTITIONS:
        raise ValueError(f"partition 必须是 {list(_PARTITIONS)} 之一，got {config.partition!r}")
    return config


def build_arm(config: ArmConfig) -> Arm:
    """channel -> runner 装配：把 config 绑定到对应通道函数。"""
    channel_fn = _CHANNELS[config.channel]
    return partial(channel_fn, config)  # type: ignore[call-arg]
