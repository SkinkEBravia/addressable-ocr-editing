"""llm 的配置：ModelConfig、TOML 装载、.env 与凭证解析。

对应 Docs/Design/08-llm.md「ModelConfig」「凭证」节。

- TOML 一文件一模型，默认放 configs/models/，文件名即标签。
- 未知键直接报 ConfigError（防拼写漂移）。
- temperature／reasoning_effort 未配置时为 None，不由该字段添加请求参数。
- context_window 仅记录模型信息；output_length 明确设置时发送输出上限。
- key 只从环境变量读取；load_env_file 把项目根 .env 加载进进程环境。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from llm.errors import ConfigError, CredentialError

__all__ = [
    "ModelConfig",
    "PROTOCOLS",
    "load_model_config",
    "model_config_from_dict",
    "load_env_file",
    "resolve_api_key",
    "default_models_dir",
]

PROTOCOLS = ("openai-completion", "openai-response", "anthropic")

_KNOWN_KEYS = frozenset(
    {
        "protocol",
        "base_url",
        "model",
        "key_env",
        "temperature",
        "reasoning_effort",
        "context_window",
        "output_length",
        "max_transport_retries",
        "timeout",
        "extra_body",
    }
)


@dataclass(frozen=True)
class ModelConfig:
    """一个可用模型的完整描述。采样键为 None 表示未配置，不发送该参数。"""

    name: str  # 报告标签（= 文件名或调用方标签）
    protocol: str  # openai-completion | openai-response | anthropic
    base_url: str
    model: str
    key_env: str  # 存放 API key 的环境变量名（间接引用）
    temperature: float | None = None
    reasoning_effort: str | None = None
    context_window: int | None = None  # 信息性，暂不使用
    output_length: int | None = None  # 明确设置时发送为协议对应的输出上限
    max_transport_retries: int = 3
    timeout: float = 600.0
    extra_body: dict | None = None  # 端点专属参数，原样并入请求体顶层

    def as_dict(self) -> dict:
        """序列化为配置字典（report.json 落盘 / 重建用）。"""
        return {
            "protocol": self.protocol,
            "base_url": self.base_url,
            "model": self.model,
            "key_env": self.key_env,
            "temperature": self.temperature,
            "reasoning_effort": self.reasoning_effort,
            "context_window": self.context_window,
            "output_length": self.output_length,
            "max_transport_retries": self.max_transport_retries,
            "timeout": self.timeout,
            "extra_body": self.extra_body,
        }


def default_models_dir() -> Path:
    # src/llm/config.py -> parents[2] == 项目根
    return Path(__file__).resolve().parents[2] / "configs" / "models"


def model_config_from_dict(name: str, d: dict) -> ModelConfig:
    """从配置字典构建（TOML 解析与 report.json 重建共用）。"""
    unknown = set(d) - _KNOWN_KEYS
    if unknown:
        raise ConfigError(f"模型配置 {name!r} 含未知键: {sorted(unknown)}")
    try:
        protocol = d["protocol"]
        base_url = d["base_url"]
        model = d["model"]
        key_env = d["key_env"]
    except KeyError as exc:
        raise ConfigError(f"模型配置 {name!r} 缺少必需键: {exc}") from exc
    if protocol not in PROTOCOLS:
        raise ConfigError(
            f"模型配置 {name!r} 的 protocol {protocol!r} 未知（已知: {list(PROTOCOLS)}）"
        )
    return ModelConfig(
        name=name,
        protocol=protocol,
        base_url=str(base_url),
        model=str(model),
        key_env=str(key_env),
        temperature=(
            float(d["temperature"]) if d.get("temperature") is not None else None
        ),
        reasoning_effort=(
            str(d["reasoning_effort"]) if d.get("reasoning_effort") is not None else None
        ),
        context_window=(
            int(d["context_window"]) if d.get("context_window") is not None else None
        ),
        output_length=(
            int(d["output_length"]) if d.get("output_length") is not None else None
        ),
        max_transport_retries=int(d.get("max_transport_retries", 3)),
        timeout=float(d.get("timeout", 600.0)),
        extra_body=_parse_extra_body(name, d.get("extra_body")),
    )


def _parse_extra_body(name: str, value: object) -> dict | None:
    """extra_body 必须是 TOML 表；未配置时为 None，不并入请求体。"""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ConfigError(f"模型配置 {name!r} 的 extra_body 必须是表（dict）")
    return dict(value)


def load_model_config(name: str, base_dir: Path | None = None) -> ModelConfig:
    """按名字装载 configs/models/<name>.toml；含路径分隔符则按路径解析。"""
    if "/" in name or "\\" in name or name.endswith(".toml"):
        path = Path(name)
        label = path.stem
    else:
        path = Path(base_dir) if base_dir is not None else default_models_dir()
        path = path / f"{name}.toml"
        label = name
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"模型配置不存在: {path}") from exc
    return model_config_from_dict(label, tomllib.loads(raw.decode("utf-8")))


def load_env_file(path: Path | None = None) -> None:
    """把 .env（KEY=VALUE 行）加载进进程环境；已存在的环境变量不覆盖。

    在任何凭证解析之前由装配层调用一次。文件不存在则静默跳过。
    """
    path = path or (Path(__file__).resolve().parents[2] / ".env")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_api_key(config: ModelConfig) -> str:
    """从环境变量解析 API key；未设置抛 CredentialError，不发请求。"""
    key = os.environ.get(config.key_env, "").strip()
    if not key:
        raise CredentialError(
            f"环境变量 {config.key_env} 未设置（模型 {config.name!r} 的 key_env）"
        )
    return key
