"""agent 的工具配置（TOML）与装配。

对应 Docs/Design/09-tools.md「工具配置（TOML)」节。
未知键直接报错（防拼写漂移）。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from agent.numkey import (
    FindReplaceBlockedToolSet,
    FindReplaceNumkeyToolSet,
    PatchFindReplaceNoattToolSet,
    PatchFindReplaceToolSet,
    PatchFindReplaceUnstableToolSet,
    RewriteNumkeyToolSet,
)
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
from agent.standard import (
    FindReplaceAnthropicToolSet,
    FindReplaceToolSet,
    NoopToolSet,
    RewriteAnthropicToolSet,
    RewriteToolSet,
)
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

REGISTRY: dict[str, type] = {
    # ---- 当前命名：<寻址机制>[_<操作子集>][_<作用域>]，见 Docs/Design/09-tools.md ----
    "noop": NoopToolSet,
    "rewrite": RewriteToolSet,
    "patch": PatchToolSet,
    "patch_replace": PatchToolSet,  # 仅 replace，parse 层强制（见 _ALLOWED_OPS）
    "find_replace": FindReplaceToolSet,
    "swe_edit": SweEditToolSet,
    "swe_bash": SweBashToolSet,  # harness，暂不参与实验
    "rewrite_local_seq": RewriteSeqToolSet,
    "patch_local_seq": PatchSeqToolSet,
    "swe_edit_local_seq": SweEditSeqToolSet,
    "find_replace_local_seq": FindReplaceSeqToolSet,
    "patch_global_seq": PatchGlobalSeqToolSet,
    "swe_edit_global_seq": SweEditGlobalSeqToolSet,
    "find_replace_global_seq": FindReplaceGlobalSeqToolSet,
    # ---- neo 实验臂（plan/neo_experiment.md）：path 抬头 / num-key 视图 ----
    "rewrite_anthropic_style": RewriteAnthropicToolSet,
    "find_replace_anthropic_style": FindReplaceAnthropicToolSet,
    "rewrite_numkey": RewriteNumkeyToolSet,
    "find_replace_numkey": FindReplaceNumkeyToolSet,
    "find_replace_blocked": FindReplaceBlockedToolSet,  # = find_replace_numkey + 注意力条款
    "patch_find_replace": PatchFindReplaceToolSet,  # 仅块内 find_replace，parse 层强制
    "patch_find_replace_noatt": PatchFindReplaceNoattToolSet,  # 同上，无注意力条款
    "patch_find_replace_unstable": PatchFindReplaceUnstableToolSet,  # 位置性行号 key
    # ---- 历史包袱：旧命名保留为别名，**勿用于新实验** ----
    # 工具集名进入 resume 键、磁带路径与 report 的 arm 键，删除会使既有 run
    # 无法 resume / replay / report-only。仅为读回历史 run 保留。
    "rewrite_seq": RewriteSeqToolSet,
    "patch_seq": PatchSeqToolSet,
    "swe_edit_seq": SweEditSeqToolSet,
    "find_replace_seq": FindReplaceSeqToolSet,
}

_LEGACY_TOOLSET_NAMES = frozenset({
    "rewrite_seq", "patch_seq", "swe_edit_seq", "find_replace_seq",
})
"""旧命名。新实验请用 `*_local_seq`；见 README「工具集命名」。"""

_ALLOWED_OPS: dict[str, frozenset[str]] = {
    "patch_replace": frozenset({"replace"}),
}
"""注册表键 -> 真正被强制的操作白名单（parse 层拒绝白名单外操作）。"""
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
    if config.toolset in ("patch", "patch_replace"):
        return cls(
            partition_kind=config.partition,
            block_size=config.block_size,
            apply_mode=config.apply_mode,
            hidden_ops=frozenset(config.hide_ops),
            allowed_ops=_ALLOWED_OPS.get(config.toolset),
        )
    if config.toolset in ("patch_local_seq", "patch_seq"):
        return cls(
            partition_kind=config.partition,
            block_size=config.block_size,
            apply_mode=config.apply_mode,
            hidden_ops=frozenset(config.hide_ops),
        )
    return cls()
