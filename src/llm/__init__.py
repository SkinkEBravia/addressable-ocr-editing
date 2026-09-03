"""llm：LLM 访问层——ModelConfig、messages 接口、协议适配器、StubClient。

设计规格见 Docs/Design/08-llm.md。
"""

from llm.client import LLMClient, build_client
from llm.config import (
    ModelConfig,
    load_env_file,
    load_model_config,
    model_config_from_dict,
    resolve_api_key,
)
from llm.errors import ConfigError, CredentialError, Failure, LLMError
from llm.stub import StubClient
from llm.types import Completion, Message, Usage

__all__ = [
    "LLMClient",
    "build_client",
    "ModelConfig",
    "load_model_config",
    "model_config_from_dict",
    "load_env_file",
    "resolve_api_key",
    "LLMError",
    "Failure",
    "ConfigError",
    "CredentialError",
    "StubClient",
    "Message",
    "Completion",
    "Usage",
]
