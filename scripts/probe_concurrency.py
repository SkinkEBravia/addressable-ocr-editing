"""并发探针：对当前模型端点打 N 路并发小请求，报告成功率 / 时延 / TPS。

用法：uv run python scripts/probe_concurrency.py [--model glm-5.3-flash] [--levels 1,2,4,8,16]

诊断工具，非生产路径：直接 httpx 打端点（max_tokens 限小），不经过适配器。
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llm import load_env_file, load_model_config, resolve_api_key  # noqa: E402


def _one(client: httpx.Client, url: str, headers: dict, model: str) -> tuple[bool, float, int]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
        "max_tokens": 16,
    }
    t0 = time.monotonic()
    try:
        r = client.post(url, json=payload, headers=headers)
        dt = time.monotonic() - t0
        if r.status_code != 200:
            return (False, dt, 0)
        usage = r.json().get("usage") or {}
        return (True, dt, int(usage.get("completion_tokens") or 0))
    except httpx.HTTPError:
        return (False, time.monotonic() - t0, 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="glm-5.3-flash")
    parser.add_argument("--levels", default="1,2,4,8,16")
    args = parser.parse_args()

    load_env_file()
    cfg = load_model_config(args.model)
    key = resolve_api_key(cfg)
    url = f"{cfg.base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    for n in [int(x) for x in args.levels.split(",")]:
        with httpx.Client(timeout=httpx.Timeout(180.0)) as client:
            t0 = time.monotonic()
            with ThreadPoolExecutor(max_workers=n) as pool:
                results = list(pool.map(lambda _: _one(client, url, headers, cfg.model), range(n)))
            wall = time.monotonic() - t0
        ok = [r for r in results if r[0]]
        lat = [r[1] for r in ok]
        tokens = sum(r[2] for r in ok)
        line = (
            f"n={n:>2}  ok={len(ok)}/{n}  wall={wall:5.1f}s"
            f"  lat(avg/min/max)={statistics.mean(lat):5.1f}/{min(lat):5.1f}/{max(lat):5.1f}s"
            if ok
            else f"n={n:>2}  ok=0/{n}  wall={wall:5.1f}s"
        )
        if ok and wall > 0:
            line += f"  tps(sum out tok / wall)={tokens / wall:6.1f}"
        print(line, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
