"""anthropic 协议适配器：POST {base_url}/v1/messages。

对应 Docs/Design/08-llm.md「协议适配器」节（优先协议之一）。

- system 消息 ⇒ 顶层 `system` 字段（多条拼接）；messages 只含 user/assistant。
- `max_tokens` 强制：`ModelConfig.output_length` 必须显式给出，否则 ConfigError。
- `reasoning_effort` v1 不下发：配置即 ConfigError（不静默忽略，见 08 规则）。
- usage：input_tokens / output_tokens；Anthropic 不单列思考 token
  （含在 output_tokens 内）⇒ reasoning_tokens = None。
- 流式：on_delta 非空 ⇒ stream=true；content_block_delta（text_delta /
  thinking_delta）增量进回调；usage 取 message_start + message_delta 事件。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import httpx

from llm.adapters._transport import (
    call_with_retries,
    iter_sse_data_lines,
    raise_for_status,
)
from llm.config import ModelConfig
from llm.errors import ConfigError, LLMError
from llm.types import Completion, Message, Usage

__all__ = ["AnthropicClient"]

_ANTHROPIC_VERSION = "2023-06-01"


def _build_payload(config: ModelConfig, messages: list[Message]) -> dict:
    if config.output_length is None:
        raise ConfigError("anthropic 协议必须显式 output_length（作为 max_tokens 下发）")
    if config.reasoning_effort is not None:
        raise ConfigError("anthropic 适配器 v1 不支持 reasoning_effort（不下发、不静默忽略）")
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    payload: dict = {
        "model": config.model,
        "max_tokens": config.output_length,
        "messages": [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system"
        ],
    }
    if system:
        payload["system"] = system
    if config.temperature is not None:
        payload["temperature"] = config.temperature
    return payload


def _usage_from_dict(usage: object) -> Usage | None:
    """端点 usage -> Usage；缺失/畸形为 None（不做本地估算）。

    Anthropic 口径：input_tokens 只计未命中缓存部分，缓存量单列在
    cache_creation_input_tokens / cache_read_input_tokens——为与 OpenAI 系
    协议的 prompt_tokens 口径对齐，input_tokens 取三者之和（皆为端点字段，
    缓存计费差异留 raw 审计）。
    """
    if not isinstance(usage, dict):
        return None
    parts = [
        usage.get(k)
        for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    ]
    output_tokens = usage.get("output_tokens")
    if not any(isinstance(p, int) for p in parts) or not isinstance(output_tokens, int):
        return None
    return Usage(
        input_tokens=sum(p for p in parts if isinstance(p, int)),
        output_tokens=output_tokens,
    )


class AnthropicClient:
    """Anthropic Messages 兼容端点的 LLMClient 实现（httpx 同步）。

    传入 ``http_client`` 时由调用方持有其生命周期，便于测试注入 mock。
    """

    def __init__(
        self,
        config: ModelConfig,
        api_key: str,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._client = http_client

    def _headers(self) -> dict:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }

    def complete(
        self,
        messages: list[Message],
        *,
        on_delta: Callable[[str], None] | None = None,
    ) -> Completion:
        payload = _build_payload(self._config, messages)
        url = f"{self._config.base_url.rstrip('/')}/v1/messages"
        t0 = time.monotonic()
        if self._client is not None:
            comp = call_with_retries(
                self._config,
                lambda a: self._once(self._client, url, payload, on_delta, a),
            )
        else:
            with httpx.Client(timeout=self._config.timeout) as client:
                comp = call_with_retries(
                    self._config,
                    lambda a: self._once(client, url, payload, on_delta, a),
                )
        return Completion(
            text=comp.text,
            usage=comp.usage,
            raw=comp.raw,
            elapsed_s=time.monotonic() - t0,
        )

    # -- 单次调用 -----------------------------------------------------------

    def _once(
        self,
        client: httpx.Client,
        url: str,
        payload: dict,
        on_delta: Callable[[str], None] | None,
        attempts: int,
    ) -> Completion:
        if on_delta is None:
            response = client.post(url, json=payload, headers=self._headers())
            raise_for_status(response)
            return self._parse(response, attempts)
        return self._stream(client, url, payload, on_delta, attempts)

    def _parse(self, response: httpx.Response, attempts: int) -> Completion:
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError(
                "响应体不是合法 JSON", kind="bad_response", attempts=attempts
            ) from exc
        if not isinstance(data, dict):
            raise LLMError("响应体不是 JSON 对象", kind="bad_response", attempts=attempts)
        content = data.get("content")
        if not isinstance(content, list):
            raise LLMError("响应缺少 content 数组", kind="bad_response", attempts=attempts)
        parts = [
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        if not parts:
            raise LLMError(
                "响应 content 中没有 text 块", kind="bad_response", attempts=attempts
            )
        usage_dict = data.get("usage")
        return Completion(
            text="".join(parts), usage=_usage_from_dict(usage_dict), raw=data
        )

    def _stream(
        self,
        client: httpx.Client,
        url: str,
        payload: dict,
        on_delta: Callable[[str], None],
        attempts: int,
    ) -> Completion:
        payload = {**payload, "stream": True}
        text_parts: list[str] = []
        usage_acc: dict = {}
        with client.stream(
            "POST", url, json=payload, headers=self._headers()
        ) as response:
            raise_for_status(response)
            for data in iter_sse_data_lines(response):
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue  # 半行 / 心跳，跳过
                if not isinstance(obj, dict):
                    continue
                event = obj.get("type")
                if event == "content_block_delta":
                    delta = obj.get("delta") or {}
                    piece = delta.get("text")
                    thinking = delta.get("thinking")
                    if isinstance(piece, str) and piece:
                        text_parts.append(piece)
                        on_delta(piece)
                    elif isinstance(thinking, str) and thinking:
                        on_delta(thinking)  # 思考增量同样可观测
                elif event == "message_start":
                    usage_acc.update((obj.get("message") or {}).get("usage") or {})
                elif event == "message_delta":
                    usage_acc.update(obj.get("usage") or {})
        return Completion(
            text="".join(text_parts),
            usage=_usage_from_dict(usage_acc),
            raw={"stream": True, "usage": usage_acc},
        )
