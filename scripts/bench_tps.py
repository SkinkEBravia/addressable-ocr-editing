"""端点生成速率实测：复读任务（输出量可预测 ≈2k token），TPS = 端点 output_tokens / 墙钟。

用法：uv run python scripts/bench_tps.py [配置名...]（缺省全部主配置+降级配置）

口径：
- 复读材料取自 icdar2017 dev en 目标文章的前若干 chunk（约 8k 字符 ≈ 2k token），
  输出量 = 输入材料量，可预测；同一 prompt 对所有配置一致（公平性）。
- token 数一律取端点 usage（不本地估算）；TTFT（首 delta 时间）单列；流式请求。
"""

from __future__ import annotations

import dataclasses
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llm import Message, build_client, load_env_file, load_model_config  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
_DATA = (
    ROOT
    / "related_source" / "HIPE-OCRepair-2026-data-0.9.5" / "data"
    / "v0.9" / "icdar2017" / "en"
)

TARGET_CHARS = 8000  # ≈ 2k token 输出

DEFAULT_CONFIGS = [
    "glm-5.3-flash",
    "glm-5.3-flash-completion",
    "deepseek-v4-flash",
    "deepseek-v4-flash-completion",
]

REPS = 2
TIMEOUT = 240.0


def _material() -> str:
    """取目标文章（eng_periodical-3）开头约 8k 字符的 OCR 文本作复读材料。"""
    path = next(_DATA.glob("*_dev_*.jsonl"))
    parts: list[str] = []
    total = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            fn = row["document_metadata"].get("primary_dataset_filename") or ""
            if "eng_periodical-3" not in fn:
                continue
            text = row["ocr_hypothesis"]["transcription_unit"]
            parts.append(text)
            total += len(text)
            if total >= TARGET_CHARS:
                break
    return "\n".join(parts)


def bench_once(name: str, material: str) -> dict | None:
    cfg = dataclasses.replace(load_model_config(name), timeout=TIMEOUT)
    client = build_client(cfg)
    prompt = (
        "Repeat the text between the markers verbatim. "
        "Output only the repeated text, nothing else.\n"
        f"--- TEXT ---\n{material}\n--- END ---"
    )
    first_delta: float | None = None
    t0 = time.monotonic()

    def on_delta(text: str) -> None:
        nonlocal first_delta
        if first_delta is None:
            first_delta = time.monotonic() - t0

    try:
        completion = client.complete([Message("user", prompt)], on_delta=on_delta)
    except Exception as exc:
        print(f"  {name}: FAIL {type(exc).__name__} {str(exc)[:120]}", flush=True)
        return None
    elapsed = time.monotonic() - t0
    usage = completion.usage
    out_tokens = usage.output_tokens if usage else None
    reasoning = usage.reasoning_tokens if usage else None
    # 复读保真度粗检：输出应包含材料的首尾片段
    fidelity = material[:50] in completion.text and material[-50:] in completion.text
    return {
        "elapsed_s": round(elapsed, 1),
        "ttft_s": round(first_delta or 0.0, 1),
        "out_tokens": out_tokens,
        "reasoning_tokens": reasoning,
        "tps": round(out_tokens / elapsed, 1) if out_tokens else None,
        "fidelity": fidelity,
    }


def main() -> int:
    load_env_file()
    names = sys.argv[1:] or DEFAULT_CONFIGS
    material = _material()
    print(f"复读材料: {len(material)} chars（≈{len(material) // 4} token）", flush=True)
    rows: dict[str, list[dict]] = {n: [] for n in names}
    for rep in range(REPS):
        for name in names:
            r = bench_once(name, material)
            if r:
                rows[name].append(r)
                print(f"  [{rep + 1}/{REPS}] {name}: {r}", flush=True)
    print("\n== 汇总（端点 usage 口径，mean over reps）==")
    print(f"{'config':<38} {'TTFT s':>7} {'out tok':>8} {'TPS':>7} {'reason%':>8} {'保真':>4}")
    for name, rs in rows.items():
        if not rs:
            continue
        ttft = statistics.mean(r["ttft_s"] for r in rs)
        tok = statistics.mean(r["out_tokens"] for r in rs if r["out_tokens"])
        tps_vals = [r["tps"] for r in rs if r["tps"]]
        tps = statistics.mean(tps_vals) if tps_vals else 0.0
        reasoning = [r["reasoning_tokens"] for r in rs if r["reasoning_tokens"] is not None]
        share = f"{statistics.mean(reasoning) / tok * 100:.0f}%" if reasoning and tok else "-"
        fid = "OK" if all(r["fidelity"] for r in rs) else "差"
        print(f"{name:<38} {ttft:>7.1f} {tok:>8.0f} {tps:>7.1f} {share:>8} {fid:>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
