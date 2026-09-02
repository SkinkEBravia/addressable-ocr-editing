"""测试 1：LLM 真实请求冒烟（live）。

确认 LLM 对话系统本身正常：对每个凭证可用的模型配置发一条极小
system+user 请求，断言返回文本非空、usage 取自端点。

默认不进全量测试（marker live，见 pyproject）；手动启用：

    uv run pytest -m live tests/test_llm_live.py
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from llm import (
    CredentialError,
    Message,
    build_client,
    load_env_file,
    load_model_config,
)

ROOT = Path(__file__).resolve().parents[1]
# 主配置（优先协议）；*-completion.toml 为降级配置，另行单独冒烟
MODEL_CONFIGS = sorted(
    p.stem for p in (ROOT / "configs" / "models").glob("*.toml")
)


@pytest.mark.live
@pytest.mark.parametrize("name", MODEL_CONFIGS)
def test_live_minimal_roundtrip(name: str):
    load_env_file()
    try:
        client = build_client(load_model_config(name))
    except CredentialError:
        pytest.skip(f"{name}: 凭证未配置")
    t0 = time.monotonic()
    completion = client.complete(
        [Message("system", "You are a test probe."), Message("user", "Reply with exactly: OK")]
    )
    elapsed = time.monotonic() - t0
    assert completion.text and completion.text.strip(), "空响应"
    assert completion.usage is not None, "端点未返回 usage（计数只认端点值）"
    assert completion.usage.output_tokens > 0
    print(f"\n[live] {name}: {elapsed:.1f}s, usage={completion.usage}")


@pytest.mark.live
@pytest.mark.parametrize("name", MODEL_CONFIGS)
def test_live_streaming_roundtrip(name: str):
    """流式通道：delta 有增量、usage 仍来自端点。"""
    load_env_file()
    try:
        client = build_client(load_model_config(name))
    except CredentialError:
        pytest.skip(f"{name}: 凭证未配置")
    deltas: list[str] = []
    completion = client.complete(
        [Message("user", "Count: 1 2 3")], on_delta=deltas.append
    )
    assert deltas, "流式请求无任何 delta"
    assert completion.text and completion.text.strip()
    assert completion.usage is not None
