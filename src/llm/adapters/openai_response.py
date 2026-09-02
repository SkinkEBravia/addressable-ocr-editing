"""openai-response 协议适配器：POST {base_url}/responses。

对应 Docs/Design/08-llm.md「协议适配器」节（优先协议之一）。

- system 消息 ⇒ 顶层 `instructions` 字段（多条拼接）。
- user / assistant 消息 ⇒ `input` 数组（content 为 input_text / output_text 部件）。
- reasoning_effort ⇒ `reasoning.effort`。
- usage：input_tokens / output_tokens；reasoning_tokens 从
  usage.output_tokens_details.reasoning_tokens 提取。
- 流式：on_delta 非空 ⇒ stream=true；response.output_text.delta /
  response.reasoning_text.delta 增量进回调；usage 取 response.completed 事件。
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

__all__ = ["OpenAIResponseClient"]

_REASONING_EFFORT_VALUES = ("low", "medium", "high")


def _build_payload(config: ModelConfig, messages: list[Message]) -> dict:
    instructions = "\n\n".join(m.content for m in messages if m.role == "system")
    input_items = []
    for m in messages:
        if m.role == "system":
            continue
        part_type = "output_text" if m.role == "assistant" else "input_text"
        input_items.append(
            {"role": m.role, "content": [{"type": part_type, "text": m.content}]}
        )
    payload: dict = {"model": config.model, "input": input_items}
    if instructions:
        payload["instructions"] = instructions
    # 缺席 = 不下发；显式值才进线格式
    if config.temperature is not None:
        payload["temperature"] = config.temperature
    if config.reasoning_effort is not None:
        if config.reasoning_effort not in _REASONING_EFFORT_VALUES:
            raise ConfigError(
                f"reasoning_effort {config.reasoning_effort!r} 非法"
                f"（{list(_REASONING_EFFORT_VALUES)}）"
            )
        payload["reasoning"] = {"effort": config.reasoning_effort}
    return payload


def _usage_from_dict(usage: object) -> Usage | None:
    """端点 usage 字段 -> Usage；缺失/畸形为 None（不做本地估算）。"""
    if not isinstance(usage, dict):
        return None
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None
    reasoning = None
    details = usage.get("output_tokens_details")
    if isinstance(details, dict) and isinstance(details.get("reasoning_tokens"), int):
        reasoning = details["reasoning_tokens"]
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning,
    )


def _text_from_output(output: object, *, attempts: int) -> str:
    """从 output 数组提取文本：type=message 项的 output_text 部件拼接。"""
    if not isinstance(output, list):
        raise LLMError("响应缺少 output 数组", kind="bad_response", attempts=attempts)
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
    if not parts:
        raise LLMError(
            "响应 output 中没有 output_text", kind="bad_response", attempts=attempts
        )
    return "".join(parts)


class OpenAIResponseClient:
    """OpenAI Responses 兼容端点的 LLMClient 实现（httpx 同步）。

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
        url = f"{self._config.base_url.rstrip('/')}/responses"
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
            raise_for_status(response)
            return self._parse(response, attempts)
        return self._stream(client, url, payload, headers, on_delta, attempts)

    def _parse(self, response: httpx.Response, attempts: int) -> Completion:
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError(
                "响应体不是合法 JSON", kind="bad_response", attempts=attempts
            ) from exc
        if not isinstance(data, dict):
            raise LLMError("响应体不是 JSON 对象", kind="bad_response", attempts=attempts)
        return Completion(
            text=_text_from_output(data.get("output"), attempts=attempts),
            usage=_usage_from_dict(data.get("usage")),
            raw=data,
        )

    def _stream(
        self,
        client: httpx.Client,
        url: str,
        payload: dict,
        headers: dict,
        on_delta: Callable[[str], None],
        attempts: int,
    ) -> Completion:
        payload = {**payload, "stream": True}
        text_parts: list[str] = []
        final_response: dict | None = None
        with client.stream(
            "POST", url, json=payload, headers=headers
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
                if event in (
                    "response.output_text.delta",
                    "response.reasoning_text.delta",
                    "response.reasoning_summary_text.delta",
                ):
                    piece = obj.get("delta")
                    if isinstance(piece, str) and piece:
                        if event == "response.output_text.delta":
                            text_parts.append(piece)
                        on_delta(piece)  # 思考增量同样可观测
                elif event in ("response.completed", "response.incomplete"):
                    resp = obj.get("response")
                    if isinstance(resp, dict):
                        final_response = resp
        usage = _usage_from_dict((final_response or {}).get("usage"))
        if final_response is not None and not text_parts:
            # 端点若不在 delta 里给文本，兜底从最终响应提取
            text = _text_from_output(final_response.get("output"), attempts=attempts)
        else:
            text = "".join(text_parts)
        return Completion(text=text, usage=usage, raw={"stream": True, "response": final_response})
