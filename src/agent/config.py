"""agent 的工具配置（TOML）与装配。

对应 Docs/Design/09-tools.md「工具配置（TOML)」节。
未知键直接报错（防拼写漂移）。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from agent.patch import PatchToolSet
from agent.sequential import (
    FindReplaceGlobalSeqToolSet,
    FindReplaceSeqToolSet,
    PatchGlobalSeqToolSet,
    PatchSeqToolSet,
    RewriteSeqToolSet,
    SweEditGlobalSeqToolSet,
    SweEditSeqToolSet,
)
from agent.standard import FindReplaceToolSet, NoopToolSet, RewriteToolSet
from agent.swe_bash import SweBashToolSet
from agent.swe_edit import SweEditToolSet
from agent.toolset import Budget, ToolSet
from llm import ConfigError

__all__ = [
    "ToolsetConfig",
    "load_toolset_config",
    "toolset_config_from_dict",
    "build_toolset",
    "default_toolsets_dir",
    "REGISTRY",
]

REGISTRY = {
    "noop": NoopToolSet,
    "rewrite": RewriteToolSet,
    "patch": PatchToolSet,
    "find_replace": FindReplaceToolSet,
    "rewrite_seq": RewriteSeqToolSet,
    "patch_seq": PatchSeqToolSet,
    "swe_edit": SweEditToolSet,
    "swe_bash": SweBashToolSet,
    "swe_edit_seq": SweEditSeqToolSet,
    "find_replace_seq": FindReplaceSeqToolSet,
    "patch_global_seq": PatchGlobalSeqToolSet,
    "swe_edit_global_seq": SweEditGlobalSeqToolSet,
    "find_replace_global_seq": FindReplaceGlobalSeqToolSet,
}
"""包内标准工具集名 -> 类。"""

_KNOWN_KEYS = frozenset(
    {"toolset", "max_turns", "token_budget", "partition", "block_size",
     "apply_mode", "hide_ops"}
)


@dataclass(frozen=True)
class ToolsetConfig:
    """工具配置：工具集 + 终止预算 + 工具集专有段。"""

    name: str  # 报告标签（= 文件名）
    toolset: str  # 包内标准工具集名（见 REGISTRY）
    max_turns: int = 1
    token_budget: int | None = None
    partition: str = "lines"  # patch 通道
    block_size: int = 400  # patch 通道（partition == "chars"）
    apply_mode: str = "atomic"  # patch 通道：atomic（默认）| best_effort
    hide_ops: tuple[str, ...] = ()  # patch 通道：从提示词隐去的操作

    def as_dict(self) -> dict:
        return {
            "toolset": self.toolset,
            "max_turns": self.max_turns,
            "token_budget": self.token_budget,
            "partition": self.partition,
            "block_size": self.block_size,
            "apply_mode": self.apply_mode,
            "hide_ops": list(self.hide_ops),
        }

    def budget(self) -> Budget:
        return Budget(max_turns=self.max_turns, token_budget=self.token_budget)


def default_toolsets_dir() -> Path:
    # src/agent/config.py -> parents[2] == 项目根
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
        apply_mode=str(d.get("apply_mode", "atomic")),
        hide_ops=tuple(str(op) for op in (d.get("hide_ops") or ())),
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
    """配置 -> 工具集装配。"""
    cls = REGISTRY[config.toolset]
    if config.toolset in ("patch", "patch_seq"):
        return cls(
            partition_kind=config.partition,
            block_size=config.block_size,
            apply_mode=config.apply_mode,
            hidden_ops=frozenset(config.hide_ops),
        )
    return cls()
