"""llm 的错误类型与失败现场。

对应 Docs/Design/08-llm.md「错误」节。

三通道：对话通道（模型修，不进本层）/ 重试通道（client 修）/ 失败通道
（人修，LLMError 携带结构化 Failure）。分类只发生在适配器层。
安全约束：API key 不进入异常消息与 Failure detail。
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["LLMError", "ConfigError", "CredentialError", "Failure", "LLM_KINDS"]

# llm 阶段的失败类别。tool / extract 阶段的 kind 自由命名（见 09）。
LLM_KINDS = (
    "timeout",  # 超时 / 网络断连 / 流式停滞（看门狗掐流），重试耗尽后
    "rate_limit",  # HTTP 429
    "server",  # HTTP 5xx
    "auth",  # HTTP 401 / 403（不重试）
    "rejected",  # 其余 HTTP 非 2xx（不重试）
    "protocol_mismatch",  # 2xx 但形状不符协议（不重试）
    "incomplete",  # 流式收尾无任何 output 文本（不重试）
)


@dataclass(frozen=True)
class Failure:
    """失败现场：落盘磁带的 failure 段，debug 不依赖 stderr 追忆。"""

    stage: str  # llm | tool | extract
    kind: str
    message: str  # 人读，不含密钥
    http_status: int | None = None
    attempts: int = 1  # 含重试的总尝试次数
    elapsed_s: float | None = None  # 从发起到放弃的墙钟
    detail: dict = field(default_factory=dict)  # 现场：事件计数 / 终结事件 / body 摘录等

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "kind": self.kind,
            "message": self.message,
            "http_status": self.http_status,
            "attempts": self.attempts,
            "elapsed_s": self.elapsed_s,
            "detail": self.detail,
        }

    @staticmethod
    def from_dict(d: dict) -> "Failure":
        return Failure(
            stage=str(d["stage"]),
            kind=str(d["kind"]),
            message=str(d["message"]),
            http_status=d.get("http_status"),
            attempts=int(d.get("attempts", 1)),
            elapsed_s=d.get("elapsed_s"),
            detail=dict(d.get("detail") or {}),
        )


class LLMError(Exception):
    """LLM 调用失败（失败通道）。failure 携带完整现场。"""

    def __init__(self, failure: Failure) -> None:
        if failure.stage == "llm" and failure.kind not in LLM_KINDS:
            raise ValueError(f"unknown llm failure kind: {failure.kind!r}")
        super().__init__(failure.message)
        self.failure = failure

    @property
    def kind(self) -> str:
        return self.failure.kind

    @property
    def status(self) -> int | None:
        return self.failure.http_status

    @property
    def attempts(self) -> int:
        return self.failure.attempts


class ConfigError(Exception):
    """模型 / 工具配置错误：未知键、协议不支持的采样键、未实现的协议等。"""


class CredentialError(Exception):
    """凭证缺失：key_env 未设置。不发请求。"""
