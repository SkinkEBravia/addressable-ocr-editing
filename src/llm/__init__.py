"""llm：LLM 访问层（LLMClient 协议 + DeepSeek 实现）。"""

from llm.client import Completion, LLMClient, Usage
from llm.deepseek import DeepSeekClient
from llm.errors import LLMError

__all__ = [
    "Usage",
    "Completion",
    "LLMClient",
    "DeepSeekClient",
    "LLMError",
]
