"""llm 配置与凭证的测试（Docs/Design/08-llm.md「验收」）。"""

from __future__ import annotations

import pytest

from llm import (
    ConfigError,
    CredentialError,
    ModelConfig,
    load_model_config,
    model_config_from_dict,
    resolve_api_key,
)


def _minimal() -> dict:
    return {
        "protocol": "openai-completion",
        "base_url": "https://example.com",
        "model": "m",
        "key_env": "TEST_LLM_KEY",
    }


def test_minimal_config_sampling_keys_absent():
    cfg = model_config_from_dict("m", _minimal())
    assert cfg.temperature is None
    assert cfg.reasoning_effort is None
    assert cfg.context_window is None
    assert cfg.output_length is None


def test_unknown_key_rejected():
    with pytest.raises(ConfigError, match="未知键"):
        model_config_from_dict("m", {**_minimal(), "temprature": 0.2})  # 拼写漂移


def test_unknown_protocol_rejected():
    with pytest.raises(ConfigError, match="protocol"):
        model_config_from_dict("m", {**_minimal(), "protocol": "openapi"})


def test_missing_required_key_rejected():
    d = _minimal()
    del d["key_env"]
    with pytest.raises(ConfigError, match="缺少必需键"):
        model_config_from_dict("m", d)


def test_load_named_config(tmp_path):
    (tmp_path / "x.toml").write_text(
        'protocol = "openai-completion"\nbase_url = "https://x"\n'
        'model = "m"\nkey_env = "K"\ntemperature = 0.2\n',
        encoding="utf-8",
    )
    cfg = load_model_config("x", base_dir=tmp_path)
    assert cfg.name == "x"
    assert cfg.temperature == 0.2


def test_missing_config_file():
    with pytest.raises(ConfigError, match="不存在"):
        load_model_config("no-such-model", base_dir="/nonexistent")


def test_resolve_api_key(monkeypatch):
    cfg = model_config_from_dict("m", _minimal())
    monkeypatch.delenv("TEST_LLM_KEY", raising=False)
    with pytest.raises(CredentialError):
        resolve_api_key(cfg)
    monkeypatch.setenv("TEST_LLM_KEY", "sk-test")
    assert resolve_api_key(cfg) == "sk-test"


def test_load_env_file(tmp_path, monkeypatch):
    from llm.config import load_env_file

    env = tmp_path / ".env"
    env.write_text("A=1\n# comment\nB = \"two\"\n", encoding="utf-8")
    monkeypatch.delenv("A", raising=False)
    monkeypatch.delenv("B", raising=False)
    load_env_file(env)
    import os

    assert os.environ["A"] == "1"
    assert os.environ["B"] == "two"
    # 已存在的不覆盖
    monkeypatch.setenv("A", "system")
    load_env_file(env)
    assert os.environ["A"] == "system"


def test_repo_model_configs_loadable():
    """configs/models/ 下的 TOML 都能过校验；主配置用优先协议（08）。"""
    preferred = {
        "glm-5.3-flash": "openai-response",
        "deepseek-v4-flash": "anthropic",
        "volc-deepseek-v4-flash": "openai-response",
    }
    for name, protocol in preferred.items():
        cfg = load_model_config(name)
        assert cfg.protocol == protocol
        assert cfg.context_window == 1048576
    for name in ("glm-5.3-flash-completion", "deepseek-v4-flash-completion"):
        cfg = load_model_config(name)
        assert cfg.protocol == "openai-completion"  # 降级配置
