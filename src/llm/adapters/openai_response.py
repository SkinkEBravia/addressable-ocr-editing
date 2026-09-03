"""openai-response 协议适配器：POST {base_url}/responses。

对应 Docs/Design/08-llm.md「协议适配器」「错误」节。

- system 消息 ⇒ 顶层 `instructions` 字段（多条拼接）。
- user / assistant 消息 ⇒ `input` 数组（content 为 input_text / output_text 部件）。
- reasoning_effort ⇒ `reasoning.effort`。
- usage：input_tokens / output_tokens；reasoning_tokens 从
  usage.output_tokens_details.reasoning_tokens 提取。
- 流式：on_delta 非空 ⇒ stream=true；response.output_text.delta /
  response.reasoning_text.delta 增量进回调；usage 取 response.completed /
  response.incomplete 事件。
- 错误分类：4xx（非 401/403）⇒ rejected；2xx 形状不符 ⇒ protocol_mismatch；
  流式收尾无 output 文本 ⇒ incomplete；空文本永不静默接受。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import httpx

from llm.adapters._transport import (
    Retryable,
    call_with_retries,
    iter_sse_data_lines,
    raise_for_status,
)
from llm.config import ModelConfig
from llm.errors import ConfigError, Failure, LLMError
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
    if config.output_length is not None:
        # 端点默认输出上限远低于模型能力（volc 实测默认 ≈32k，模型 384k）：
        # 显式 output_length 必须下发为 max_output_tokens，否则 reasoning
        # 烧尽默认预算 ⇒ incomplete/length（见 impl-status「验证」）
        payload["max_output_tokens"] = config.output_length
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
    match usage:
        case {"input_tokens": int(in_tok), "output_tokens": int(out_tok), **rest} if (
            not isinstance(in_tok, bool) and not isinstance(out_tok, bool)
        ):
            details = rest.get("output_tokens_details")
            reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
            return Usage(
                input_tokens=in_tok,
                output_tokens=out_tok,
                reasoning_tokens=reasoning if isinstance(reasoning, int) and not isinstance(reasoning, bool) else None,
            )
        case _:
            return None


def _text_from_output(output: object) -> str | None:
    """从 output 数组提取文本：type=message 项的 output_text 部件拼接。

    无 output 文本返回 None（调用方按 incomplete 处理）；形状不符抛
    protocol_mismatch。
    """
    if not isinstance(output, list):
        raise LLMError(
            Failure(
                stage="llm",
                kind="protocol_mismatch",
                message="响应缺少 output 数组",
            )
        )
    parts = [
        text
        for item in output
        if isinstance(item, dict) and item.get("type") == "message"
        for part in item.get("content") or ()
        if isinstance(part, dict)
        and part.get("type") == "output_text"
        and isinstance(text := part.get("text"), str)
    ]
    return "".join(parts) if parts else None


def _failed_event_error(obj: dict, *, attempts: int) -> Exception:
    """response.failed 事件 -> 异常。error.code 可映射重试通道则 Retryable。"""
    resp = obj.get("response") if isinstance(obj.get("response"), dict) else {}
    error = resp.get("error") if isinstance(resp.get("error"), dict) else {}
    code = str(error.get("code") or "")
    message = str(error.get("message") or "response.failed")
    if "rate_limit" in code:
        return Retryable(f"response.failed: {message}", kind="rate_limit")
    if "server" in code:
        return Retryable(f"response.failed: {message}", kind="server")
    return LLMError(
        Failure(
            stage="llm",
            kind="incomplete",
            message=f"response.failed: {message}",
            attempts=attempts,
            detail={"event": "response.failed", "error_code": code},
        )
    )


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
            raise_for_status(response, attempts=attempts)
            return self._parse(response, attempts)
        return self._stream(client, url, payload, headers, on_delta, attempts)

    def _parse(self, response: httpx.Response, attempts: int) -> Completion:
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
        status = str(data.get("status") or "completed")
        text = _text_from_output(data.get("output"))
        if not text:
            raise LLMError(
                Failure(
                    stage="llm",
                    kind="incomplete",
                    message=f"响应无 output 文本（status={status}）",
                    attempts=attempts,
                    detail={
                        "response_status": status,
                        "incomplete_details": data.get("incomplete_details"),
                    },
                )
            )
        return Completion(
            text=text,
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
        final_event: str | None = None
        n_data_events = 0
        with client.stream(
            "POST", url, json=payload, headers=headers
        ) as response:
            raise_for_status(response, attempts=attempts)
            for data in iter_sse_data_lines(response):
                n_data_events += 1
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
                elif event == "response.failed":
                    raise _failed_event_error(obj, attempts=attempts)
                elif event in ("response.completed", "response.incomplete"):
                    final_event = event
                    resp = obj.get("response")
                    if isinstance(resp, dict):
                        final_response = resp

        if n_data_events == 0:
            # 200 但流里一条 data 事件都没有：对方没在讲这个协议
            raise LLMError(
                Failure(
                    stage="llm",
                    kind="protocol_mismatch",
                    message="流式响应没有任何 SSE data 事件",
                    attempts=attempts,
                )
            )
        text = "".join(text_parts)
        usage = _usage_from_dict((final_response or {}).get("usage"))
        if not text and final_response is not None:
            # 端点若不在 delta 里给文本，兜底从最终响应提取
            text = _text_from_output(final_response.get("output")) or ""
        if not text:
            raise LLMError(
                Failure(
                    stage="llm",
                    kind="incomplete",
                    message=f"流式收尾无 output 文本（终结事件={final_event}）",
                    attempts=attempts,
                    detail={
                        "final_event": final_event,
                        "data_events": n_data_events,
                        "response_status": (final_response or {}).get("status"),
                        "incomplete_details": (final_response or {}).get(
                            "incomplete_details"
                        ),
                    },
                )
            )
        return Completion(
            text=text, usage=usage, raw={"stream": True, "response": final_response}
        )
