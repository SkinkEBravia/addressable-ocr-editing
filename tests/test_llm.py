"""llm 模块的测试（对应 Docs/Design/08-eval-framework.md「接口」与「边界」）。

全部通过注入假 httpx client 完成，禁止真实网络请求。
隔离约束：仓库根存在真实的 deep_seek.txt，所有用例必须显式传
``credentials_path``（tmp_path 内或不存在路径），不得触达真实凭证。
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

import llm.deepseek as deepseek_module
from llm import Completion, DeepSeekClient, LLMClient, LLMError, Usage

ENV_KEY = "sk-env-key-for-test"
FILE_KEY = "sk-file-key-for-test"
NO_FILE = Path("definitely-not-exists-deep_seek.txt")

GOOD_PAYLOAD = {
    "choices": [{"message": {"role": "assistant", "content": "修正后的文本"}}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 7},
}


class _FakeResponse:
    """最小化的 httpx.Response 替身。"""

    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeClient:
    """按脚本响应：每项为 _FakeResponse（返回）或 Exception（抛出）。"""

    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.requests: list[dict] = []

    def post(self, url: str, *, json: dict, headers: dict) -> _FakeResponse:
        self.requests.append({"url": url, "json": json, "headers": headers})
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self) -> None:  # 注入的 client 由调用方持有，这里仅满足接口
        pass


def _make_client(
    fake: _FakeClient,
    tmp_path: Path,
    *,
    max_retries: int = 3,
    **kwargs,
) -> DeepSeekClient:
    return DeepSeekClient(
        max_retries=max_retries,
        credentials_path=tmp_path / NO_FILE,
        http_client=fake,  # type: ignore[arg-type]
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _isolate_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认无环境变量 key、退避不睡眠。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(deepseek_module, "_backoff", lambda retry_index: None)


@pytest.fixture
def env_key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DEEPSEEK_API_KEY", ENV_KEY)
    return ENV_KEY


def test_protocol_conformance(env_key: str, tmp_path: Path) -> None:
    """LLMClient 是结构化协议（非 runtime_checkable），以鸭子类型验证。"""
    client = _make_client(_FakeClient([_FakeResponse(200, GOOD_PAYLOAD)]), tmp_path)
    assert callable(getattr(client, "complete", None))
    result = client.complete("x", system=None)
    assert isinstance(result, Completion) and isinstance(result.usage, Usage)


def test_complete_parses_text_and_usage(env_key: str, tmp_path: Path) -> None:
    fake = _FakeClient([_FakeResponse(200, GOOD_PAYLOAD)])
    client = _make_client(fake, tmp_path)
    result = client.complete("原始 OCR 文本")
    assert result == Completion(text="修正后的文本", usage=Usage(input_tokens=11, output_tokens=7))
    req = fake.requests[0]
    assert req["url"] == "https://api.deepseek.com/chat/completions"
    assert req["headers"]["Authorization"] == f"Bearer {ENV_KEY}"
    assert req["json"]["model"] == "deepseek-v4-flash"
    assert req["json"]["temperature"] == 0.2


def test_system_message_assembly(env_key: str, tmp_path: Path) -> None:
    fake = _FakeClient([_FakeResponse(200, GOOD_PAYLOAD), _FakeResponse(200, GOOD_PAYLOAD)])
    client = _make_client(fake, tmp_path)
    client.complete("p1", system="你是校对器")
    client.complete("p2")
    with_system, without_system = fake.requests
    assert with_system["json"]["messages"] == [
        {"role": "system", "content": "你是校对器"},
        {"role": "user", "content": "p1"},
    ]
    assert without_system["json"]["messages"] == [{"role": "user", "content": "p2"}]


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retryable_status_then_success(env_key: str, tmp_path: Path, status: int) -> None:
    fake = _FakeClient([
        _FakeResponse(status, {}),
        _FakeResponse(status, {}),
        _FakeResponse(200, GOOD_PAYLOAD),
    ])
    client = _make_client(fake, tmp_path)
    result = client.complete("x")
    assert result.text == "修正后的文本"
    assert len(fake.requests) == 3


def test_network_error_then_success(env_key: str, tmp_path: Path) -> None:
    fake = _FakeClient([httpx.ConnectError("boom"), _FakeResponse(200, GOOD_PAYLOAD)])
    client = _make_client(fake, tmp_path)
    result = client.complete("x")
    assert result.usage.output_tokens == 7
    assert len(fake.requests) == 2


def test_retry_exhaustion_raises(env_key: str, tmp_path: Path) -> None:
    fake = _FakeClient([_FakeResponse(503, {})] * 4)
    client = _make_client(fake, tmp_path, max_retries=2)
    with pytest.raises(LLMError) as excinfo:
        client.complete("x")
    # 1 次首发 + 2 次重试 = 3 次请求；第 3 次失败后不再重试
    assert len(fake.requests) == 3
    assert excinfo.value.status == 503
    assert excinfo.value.attempts == 3
    assert ENV_KEY not in str(excinfo.value)


def test_network_error_exhaustion_raises(env_key: str, tmp_path: Path) -> None:
    fake = _FakeClient([httpx.ConnectError("boom")] * 3)
    client = _make_client(fake, tmp_path, max_retries=2)
    with pytest.raises(LLMError) as excinfo:
        client.complete("x")
    assert len(fake.requests) == 3
    assert excinfo.value.status is None
    assert ENV_KEY not in str(excinfo.value)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_4xx_no_retry_raises_immediately(env_key: str, tmp_path: Path, status: int) -> None:
    fake = _FakeClient([_FakeResponse(status, {"error": "bad"})])
    client = _make_client(fake, tmp_path)
    with pytest.raises(LLMError) as excinfo:
        client.complete("x")
    assert len(fake.requests) == 1
    assert excinfo.value.status == status
    assert ENV_KEY not in str(excinfo.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"choices": [{"message": {"content": "t"}}]},  # 无 usage
        {"choices": [{"message": {"content": "t"}}], "usage": {"prompt_tokens": 1}},  # usage 缺字段
        {"usage": {"prompt_tokens": 1, "completion_tokens": 2}},  # 无 choices
        {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 2}},  # 空 choices
        ValueError("not json"),  # 非法 JSON
    ],
)
def test_missing_usage_or_malformed_raises(
    env_key: str, tmp_path: Path, payload: object
) -> None:
    fake = _FakeClient([_FakeResponse(200, payload)])
    client = _make_client(fake, tmp_path)
    with pytest.raises(LLMError):
        client.complete("x")


def test_env_var_takes_priority_over_file(env_key: str, tmp_path: Path) -> None:
    cred_file = tmp_path / "deep_seek.txt"
    cred_file.write_text(f"key = {FILE_KEY}\n", encoding="utf-8")
    fake = _FakeClient([_FakeResponse(200, GOOD_PAYLOAD)])
    client = DeepSeekClient(
        credentials_path=cred_file,
        http_client=fake,  # type: ignore[arg-type]
    )
    client.complete("x")
    assert fake.requests[0]["headers"]["Authorization"] == f"Bearer {ENV_KEY}"


def test_file_fallback_key_and_base_url(tmp_path: Path) -> None:
    cred_file = tmp_path / "deep_seek.txt"
    cred_file.write_text(
        f"随便写的备注\napi_key: {FILE_KEY}\nbase_url = https://fake.example.com/v1\n",
        encoding="utf-8",
    )
    fake = _FakeClient([_FakeResponse(200, GOOD_PAYLOAD)])
    client = DeepSeekClient(
        credentials_path=cred_file,
        http_client=fake,  # type: ignore[arg-type]
    )
    client.complete("x")
    req = fake.requests[0]
    assert req["headers"]["Authorization"] == f"Bearer {FILE_KEY}"
    assert req["url"] == "https://fake.example.com/v1/chat/completions"


def test_file_base_url_overrides_default_even_with_env_key(
    env_key: str, tmp_path: Path
) -> None:
    cred_file = tmp_path / "deep_seek.txt"
    cred_file.write_text("endpoint: https://fake2.example.com\n", encoding="utf-8")
    fake = _FakeClient([_FakeResponse(200, GOOD_PAYLOAD)])
    client = DeepSeekClient(
        credentials_path=cred_file,
        http_client=fake,  # type: ignore[arg-type]
    )
    client.complete("x")
    assert fake.requests[0]["url"] == "https://fake2.example.com/chat/completions"


def test_missing_credentials_raises_without_key(tmp_path: Path) -> None:
    """无凭证时报错；消息只说明解析规则，不含任何真实 key 值。"""
    with pytest.raises(LLMError) as excinfo:
        DeepSeekClient(credentials_path=tmp_path / NO_FILE)
    message = str(excinfo.value)
    assert ENV_KEY not in message
    assert FILE_KEY not in message
    assert "sk- 开头的 key" in message  # 仅含规则说明文字


def test_file_without_key_raises(tmp_path: Path) -> None:
    cred_file = tmp_path / "deep_seek.txt"
    cred_file.write_text("这里没有 key，只有备注\n", encoding="utf-8")
    with pytest.raises(LLMError):
        DeepSeekClient(credentials_path=cred_file)


def test_error_message_never_contains_file_key(tmp_path: Path) -> None:
    """失败路径（重试耗尽）上，异常消息不得泄露文件中的 key。"""
    cred_file = tmp_path / "deep_seek.txt"
    cred_file.write_text(f"key = {FILE_KEY}\n", encoding="utf-8")
    fake = _FakeClient([_FakeResponse(429, {})] * 5)
    client = DeepSeekClient(
        credentials_path=cred_file,
        http_client=fake,  # type: ignore[arg-type]
    )
    with pytest.raises(LLMError) as excinfo:
        client.complete("x")
    assert FILE_KEY not in str(excinfo.value)
    assert excinfo.value.status == 429
