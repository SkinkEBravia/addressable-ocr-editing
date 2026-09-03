"""configs/ 目录的一致性：每个 TOML 都能装载并装配（防命名漂移）。

静态检查管不到「配置名字符串 ↔ 文件名」的一致性，这个测试兜住。
"""

from __future__ import annotations

from agent import build_toolset, load_toolset_config
from agent.config import default_toolsets_dir
from llm import load_model_config
from llm.config import default_models_dir


def test_all_toolset_configs_load_and_build():
    configs = sorted(default_toolsets_dir().glob("*.toml"))
    assert configs, "configs/toolsets/ 下应有配置"
    for path in configs:
        cfg = load_toolset_config(path.stem)
        toolset = build_toolset(cfg)  # 装配不抛错
        assert toolset.prompt_clause is not None


def test_all_model_configs_load():
    configs = sorted(default_models_dir().glob("*.toml"))
    assert configs, "configs/models/ 下应有配置"
    for path in configs:
        mc = load_model_config(path.stem)
        assert mc.protocol and mc.model and mc.key_env
