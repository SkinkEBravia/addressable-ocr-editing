"""DeepSeek 实现：OpenAI 兼容端点（POST {base_url}/chat/completions），httpx 同步客户端。

凭证解析顺序（见 Docs/Design/08-eval-framework.md「边界」）：

1. 环境变量 ``DEEPSEEK_API_KEY``
2. 项目根的 ``deep_seek.txt``（自由格式文本，正则提取 ``sk-`` 开头的 key；
   文件中若含 ``http(s)://`` URL 则以之为 base_url，覆盖默认值）

安全约束：API key 不打印、不进日志、不进异常消息。
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from llm.client import Completion, Usage
from llm.errors import LLMError

__all__ = ["DeepSeekClient"]

_DEFAULT_BASE_URL = "https://api.deepseek.com"
_API_KEY_ENV = "DEEPSEEK_API_KEY"
_CREDENTIALS_FILENAME = "deep_seek.txt"

_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]+")
_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")

_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_MAX_SECONDS = 60.0


@dataclass(frozen=True)
class _Credentials:
    api_key: str
    base_url: str | None  # None 表示使用默认端点


def _project_root() -> Path:
    # src/llm/deepseek.py -> parents[2] == 项目根
    return Path(__file__).resolve().parents[2]


def _read_credentials_file(path: Path) -> tuple[str | None, str | None]:
    """从自由格式凭证文件提取 (api_key, base_url)，均为可选。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, None
    key_match = _KEY_PATTERN.search(text)
    url_match = _URL_PATTERN.search(text)
    return (
        key_match.group(0) if key_match else None,
        url_match.group(0) if url_match else None,
    )


def _resolve_credentials(credentials_path: Path) -> _Credentials:
    """环境变量优先，deep_seek.txt 回退；文件中的 base_url 始终优先于默认值。"""
    file_key: str | None = None
    file_url: str | None = None
    if credentials_path.is_file():
        file_key, file_url = _read_credentials_file(credentials_path)

    env_key = os.environ.get(_API_KEY_ENV, "").strip()
    api_key = env_key or file_key
    if not api_key:
        raise LLMError(
            f"未找到 DeepSeek API key：环境变量 {_API_KEY_ENV} 未设置，"
            f"且 {credentials_path.name} 中无 sk- 开头的 key"
        )
    return _Credentials(api_key=api_key, base_url=file_url)


def _build_messages(prompt: str, system: str | None) -> list[dict[str, str]]:
    """system 非空时放 system role，prompt 放 user role。"""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def _backoff(retry_index: int) -> None:
    """指数退避：retry_index 从 1 开始（1s, 2s, 4s, ...，封顶 60s）。测试中可 monkeypatch。"""
    delay = min(_BACKOFF_MAX_SECONDS, _BACKOFF_BASE_SECONDS * 2 ** (retry_index - 1))
    time.sleep(delay)


def _parse_completion(response: httpx.Response, *, attempts: int) -> Completion:
    """解析 OpenAI 兼容响应；usage 缺失或类型不符时抛 LLMError（协议要求 usage 必须真实）。"""
    try:
        data = response.json()
    except ValueError as exc:
        raise LLMError("响应体不是合法 JSON", attempts=attempts) from exc
    try:
        text = data["choices"][0]["message"]["content"]
        usage = data["usage"]
        input_tokens = usage["prompt_tokens"]
        output_tokens = usage["completion_tokens"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("响应缺少 choices 或 usage 字段", attempts=attempts) from exc
    if not isinstance(text, str):
        raise LLMError("响应 content 不是字符串", attempts=attempts)
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        raise LLMError("响应 usage 字段不是整数", attempts=attempts)
    return Completion(
        text=text,
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class DeepSeekClient:
    """LLMClient 协议的 DeepSeek 实现。

    - 429 / 5xx / 网络错误（httpx.TransportError）：指数退避重试，
      最多重试 ``max_retries`` 次（总尝试 = 1 + max_retries），耗尽抛 LLMError。
    - 其他 4xx 与响应解析失败：不重试，直接抛 LLMError。
    - 传入 ``http_client`` 时由调用方持有其生命周期，便于测试注入 mock。
    """

    def __init__(
        self,
        model: str = "deepseek-v4-flash",
        temperature: float = 0.2,
        timeout: float = 600,
        max_retries: int = 3,
        *,
        base_url: str | None = None,
        credentials_path: Path | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        credentials = _resolve_credentials(
            credentials_path or (_project_root() / _CREDENTIALS_FILENAME)
        )
        self._api_key = credentials.api_key
        self._base_url = (base_url or credentials.base_url or _DEFAULT_BASE_URL).rstrip("/")
        self._model = model
        self._temperature = temperature
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = http_client

    def complete(self, prompt: str, *, system: str | None = None) -> Completion:
        payload = {
            "model": self._model,
            "temperature": self._temperature,
            "messages": _build_messages(prompt, system),
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/chat/completions"
        if self._client is not None:
            return self._request_with_retry(self._client, url, payload, headers)
        with httpx.Client(timeout=self._timeout) as client:
            return self._request_with_retry(client, url, payload, headers)

    def _request_with_retry(
        self,
        client: httpx.Client,
        url: str,
        payload: dict,
        headers: dict[str, str],
    ) -> Completion:
        attempts = 0
        while True:
            attempts += 1
            try:
                response = client.post(url, json=payload, headers=headers)
            except httpx.TransportError as exc:
                if attempts > self._max_retries:
                    raise LLMError(
                        f"网络错误：{type(exc).__name__}", attempts=attempts
                    ) from exc
                _backoff(attempts)
                continue
            status = response.status_code
            if status == 429 or status >= 500:
                if attempts > self._max_retries:
                    raise LLMError("服务不可用，重试耗尽", status=status, attempts=attempts)
                _backoff(attempts)
                continue
            if status != 200:
                raise LLMError("请求被拒绝（不可重试）", status=status, attempts=attempts)
            return _parse_completion(response, attempts=attempts)
