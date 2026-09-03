"""openai-completion 协议适配器：POST {base_url}/chat/completions。

对应 Docs/Design/08-llm.md「协议适配器」「错误」节。

- 线格式互转与 usage 提取，不改写内容。
- 采样键缺席（None）= 不下发该参数。
- reasoning_tokens 从 usage.completion_tokens_details.reasoning_tokens 提取。
- 流式：传入 on_delta 时启用 stream（含 stream_options.include_usage），
  每个增量（content 与 reasoning_content）回调给调用方。
- 错误分类：4xx（非 401/403）⇒ rejected；2xx 形状不符 ⇒ protocol_mismatch；
  流式收尾无文本 ⇒ incomplete；空文本永不静默接受。
- 安全约束：API key 不打印、不进异常消息与 Failure detail。
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
from llm.errors import ConfigError, Failure, LLMError
from llm.types import Completion, Message, Usage

__all__ = ["OpenAICompletionClient"]

_REASONING_EFFORT_VALUES = ("low", "medium", "high")


def _build_payload(config: ModelConfig, messages: list[Message]) -> dict:
    payload: dict = {
        "model": config.model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
    }
    # 缺席 = 不下发；显式值才进线格式
    if config.temperature is not None:
        payload["temperature"] = config.temperature
    if config.output_length is not None:
        # 显式 output_length 下发为 max_tokens（端点默认上限可能远低于模型能力）
        payload["max_tokens"] = config.output_length
    if config.reasoning_effort is not None:
        if config.reasoning_effort not in _REASONING_EFFORT_VALUES:
            raise ConfigError(
                f"reasoning_effort {config.reasoning_effort!r} 非法"
                f"（{list(_REASONING_EFFORT_VALUES)}）"
            )
        payload["reasoning_effort"] = config.reasoning_effort
    return payload


def _usage_from_dict(usage: object) -> Usage | None:
    """端点 usage 字段 -> Usage；缺失/畸形为 None（不做本地估算）。"""
    if not isinstance(usage, dict):
        return None
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None
    reasoning = None
    details = usage.get("completion_tokens_details")
    if isinstance(details, dict) and isinstance(details.get("reasoning_tokens"), int):
        reasoning = details["reasoning_tokens"]
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning,
    )


def _parse_completion(response: httpx.Response, *, attempts: int) -> Completion:
    try:
        data = response.json()
    except ValueError as exc:
        raise LLMError(
            Failure(
                stage="llm",
                kind="protocol_mismatch",
                message="响应体不是合法 JSON",
                attempts=attempts,
                detail={"body_excerpt": response.text[:300]},
            )
        ) from exc
    if not isinstance(data, dict):
        raise LLMError(
            Failure(
                stage="llm",
                kind="protocol_mismatch",
                message="响应体不是 JSON 对象",
                attempts=attempts,
            )
        )
    match data.get("choices"):
        case [{"message": {"content": str(text)}}, *_] if text:
            return Completion(text=text, usage=_usage_from_dict(data.get("usage")), raw=data)
        case [{"message": {"content": str()}}, *_]:
            raise LLMError(
                Failure(
                    stage="llm",
                    kind="incomplete",
                    message="响应 content 为空文本",
                    attempts=attempts,
                )
            )
        case [{"message": {"content": not_str}}, *_]:
            raise LLMError(
                Failure(
                    stage="llm",
                    kind="protocol_mismatch",
                    message="响应 content 不是字符串",
                    attempts=attempts,
                )
            )
        case _:
            raise LLMError(
                Failure(
                    stage="llm",
                    kind="protocol_mismatch",
                    message="响应缺少 choices[0].message.content",
                    attempts=attempts,
                )
            )


class OpenAICompletionClient:
    """OpenAI Chat Completions 兼容端点的 LLMClient 实现（httpx 同步）。

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

    def complete(
        self,
        messages: list[Message],
        *,
        on_delta: Callable[[str], None] | None = None,
    ) -> Completion:
        payload = _build_payload(self._config, messages)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._config.base_url.rstrip('/')}/chat/completions"
        t0 = time.monotonic()
        if self._client is not None:
            comp = call_with_retries(
                self._config,
                lambda a: self._once(self._client, url, payload, headers, on_delta, a),
            )
        else:
            with httpx.Client(timeout=self._config.timeout) as client:
                comp = call_with_retries(
                    self._config,
                    lambda a: self._once(client, url, payload, headers, on_delta, a),
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
        headers: dict,
        on_delta: Callable[[str], None] | None,
        attempts: int,
    ) -> Completion:
        if on_delta is None:
            response = client.post(url, json=payload, headers=headers)
            raise_for_status(response, attempts=attempts)
            return _parse_completion(response, attempts=attempts)
        return self._stream(client, url, payload, headers, on_delta, attempts)

    def _stream(
        self,
        client: httpx.Client,
        url: str,
        payload: dict,
        headers: dict,
        on_delta: Callable[[str], None],
        attempts: int,
    ) -> Completion:
        payload = {
            **payload,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        text_parts: list[str] = []
        usage_dict: dict | None = None
        n_data_events = 0
        with client.stream("POST", url, json=payload, headers=headers) as response:
            raise_for_status(response, attempts=attempts)
            for data in iter_sse_data_lines(response):
                n_data_events += 1
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue  # 半行 / 心跳，跳过
                if isinstance(obj.get("usage"), dict):
                    usage_dict = obj["usage"]
                for choice in obj.get("choices") or []:
                    delta = choice.get("delta") or {}
                    piece = delta.get("content")
                    if isinstance(piece, str) and piece:
                        text_parts.append(piece)
                        on_delta(piece)
                    thinking = delta.get("reasoning_content")
                    if isinstance(thinking, str) and thinking:
                        on_delta(thinking)  # 思考过程也可观测
        if n_data_events == 0:
            raise LLMError(
                Failure(
                    stage="llm",
                    kind="protocol_mismatch",
                    message="流式响应没有任何 SSE data 事件",
                    attempts=attempts,
                )
            )
        text = "".join(text_parts)
        if not text:
            raise LLMError(
                Failure(
                    stage="llm",
                    kind="incomplete",
                    message="流式收尾无文本",
                    attempts=attempts,
                    detail={"data_events": n_data_events},
                )
            )
        return Completion(
            text=text,
            usage=_usage_from_dict(usage_dict),
            raw={"stream": True, "usage": usage_dict},
        )
