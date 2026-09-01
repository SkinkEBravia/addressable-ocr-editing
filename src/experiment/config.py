"""experiment 的配置：ToolsetConfig（TOML）与装配。

对应 Docs/Design/09-tools.md「工具配置（TOML）」节。
未知键直接报错（防拼写漂移）。
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from llm import ConfigError
from toolsets import REGISTRY, Budget, ToolSet

__all__ = [
    "ToolsetConfig",
    "load_toolset_config",
    "toolset_config_from_dict",
    "build_toolset",
    "config_hash",
    "default_toolsets_dir",
]

_KNOWN_KEYS = frozenset(
    {"toolset", "max_turns", "token_budget", "partition", "block_size"}
)


@dataclass(frozen=True)
class ToolsetConfig:
    """工具配置：工具集 + 终止预算 + 工具集专有段。"""

    name: str  # 报告标签（= 文件名）
    toolset: str  # 包内标准工具集名（见 toolsets.REGISTRY）
    max_turns: int = 1
    token_budget: int | None = None
    partition: str = "lines"  # patch 通道
    block_size: int = 400  # patch 通道（partition == "chars"）

    def as_dict(self) -> dict:
        return {
            "toolset": self.toolset,
            "max_turns": self.max_turns,
            "token_budget": self.token_budget,
            "partition": self.partition,
            "block_size": self.block_size,
        }

    def budget(self) -> Budget:
        return Budget(max_turns=self.max_turns, token_budget=self.token_budget)


def default_toolsets_dir() -> Path:
    # src/experiment/config.py -> parents[2] == 项目根
    return Path(__file__).resolve().parents[2] / "configs" / "toolsets"


def toolset_config_from_dict(name: str, d: dict) -> ToolsetConfig:
    unknown = set(d) - _KNOWN_KEYS
    if unknown:
        raise ConfigError(f"工具配置 {name!r} 含未知键: {sorted(unknown)}")
    toolset = d.get("toolset")
    if toolset not in REGISTRY:
        raise ConfigError(
            f"工具配置 {name!r} 的 toolset {toolset!r} 未知（{sorted(REGISTRY)}）"
        )
    return ToolsetConfig(
        name=name,
        toolset=str(toolset),
        max_turns=int(d.get("max_turns", 1)),
        token_budget=(
            int(d["token_budget"]) if d.get("token_budget") is not None else None
        ),
        partition=str(d.get("partition", "lines")),
        block_size=int(d.get("block_size", 400)),
    )


def load_toolset_config(name: str, base_dir: Path | None = None) -> ToolsetConfig:
    """按名字装载 configs/toolsets/<name>.toml；含路径分隔符则按路径解析。"""
    if "/" in name or "\\" in name or name.endswith(".toml"):
        path = Path(name)
        label = path.stem
    else:
        path = Path(base_dir) if base_dir is not None else default_toolsets_dir()
        path = path / f"{name}.toml"
        label = name
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"工具配置不存在: {path}") from exc
    return toolset_config_from_dict(label, tomllib.loads(raw.decode("utf-8")))


def build_toolset(config: ToolsetConfig) -> ToolSet:
    """channel -> 工具集装配。"""
    cls = REGISTRY[config.toolset]
    if config.toolset == "patch":
        return cls(partition_kind=config.partition, block_size=config.block_size)
    return cls()


def config_hash(*configs: dict) -> str:
    """resume 的键：配置规范化 JSON 的哈希。同名配置换了内容 = 新运行。"""
    canonical = json.dumps(configs, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
