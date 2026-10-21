"""Opt-in DeepSeek smoke: two short calls, no retries, 64 output tokens each.

Run explicitly with: uv run pytest -m live tests/test_llm_live.py -q -s
Default offline runs exclude this module's marked tests.
"""

import json
import os
from dataclasses import asdict, replace

import pytest

from llm import Message, build_client, load_env_file, load_model_config

pytestmark = pytest.mark.live


@pytest.mark.parametrize("streaming", [False, True], ids=["nonstream", "stream"])
def test_deepseek_public_client_small_smoke(streaming):
    load_env_file()
    if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        pytest.skip("DEEPSEEK_API_KEY is not configured")
    config = replace(
        load_model_config("deepseek-v4-flash-completion"),
        output_length=64,
        max_transport_retries=0,
        timeout=30.0,
        extra_body={"thinking": {"type": "disabled"}},
    )
    observed = []
    result = build_client(config).complete(
        [Message("system", "Reply with exactly OK."), Message("user", "Reply OK.")],
        on_delta=observed.append if streaming else None,
    )
    assert result.text.strip() == "OK"
    assert result.usage is not None
    assert result.usage.input_tokens > 0 and result.usage.output_tokens > 0
    assert result.elapsed_s > 0
    assert bool(observed) == streaming
    print(json.dumps({"protocol": config.protocol, "model": config.model,
                      "stream": streaming, "max_output_tokens": config.output_length,
                      "max_retries": config.max_transport_retries, "reply": result.text.strip(),
                      "usage": asdict(result.usage), "elapsed_s": round(result.elapsed_s, 3)}))
