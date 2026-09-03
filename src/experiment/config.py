"""experiment 的装配小件：config_hash（resume 的键）。

对应 Docs/Design/11-experiment.md「磁带存储」节。
"""

from __future__ import annotations

import hashlib
import json

__all__ = ["config_hash"]


def config_hash(*configs: dict) -> str:
    """resume 的键：配置规范化 JSON 的哈希。同名配置换了内容 = 新运行。"""
    canonical = json.dumps(configs, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
