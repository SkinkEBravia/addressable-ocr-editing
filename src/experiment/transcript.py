"""experiment 的对话录：逐轮增量落盘（runs/<name>/raw/<task_id>/<toolset>.json）。

对应 Docs/Design/11-experiment.md「对话录」节。

- 逐轮增量落盘：每轮完成即重写该文件（原子写），中断不白费。
- 请求 messages 全文按内容哈希去重存放于 messages/ 目录。
- 文件头带 config_hash：resume 的键 = (task_id, toolset, config_hash)。
- 对话录是不可再生资产：任何清理操作不得删 raw/。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from toolsets import LoopResult, TurnRecord

__all__ = ["TranscriptWriter", "read_transcript"]


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _messages_ref(messages_dir: Path, messages: tuple) -> str:
    """messages 全文按内容哈希去重存放，返回引用。"""
    payload = [{"role": m.role, "content": m.content} for m in messages]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    path = messages_dir / f"{digest}.json"
    if not path.exists():
        _write_json_atomic(path, payload)
    return f"sha256:{digest}"


def _turn_to_dict(turn: TurnRecord, messages_dir: Path) -> dict:
    completion = turn.completion
    return {
        "index": turn.index,
        "messages_ref": _messages_ref(messages_dir, turn.request),
        "completion": {
            "text": completion.text,
            "usage": (
                None
                if completion.usage is None
                else {
                    "input_tokens": completion.usage.input_tokens,
                    "output_tokens": completion.usage.output_tokens,
                    "reasoning_tokens": completion.usage.reasoning_tokens,
                }
            ),
            "raw": completion.raw,
        },
        "tool_calls": [
            {"name": c.name, "args": c.args_text, "ok": r.ok, "feedback": r.feedback}
            for c, r in turn.calls
        ],
        "parse_error": turn.parse_error,
    }


class TranscriptWriter:
    """一个 (task, toolset) 的对话录写盘器；每轮完成即增量落盘。"""

    def __init__(self, out_dir: Path, task_id: str, toolset: str, cfg_hash: str) -> None:
        self._path = out_dir / "raw" / task_id / f"{toolset}.json"
        self._messages_dir = out_dir / "raw" / "messages"
        self._cfg_hash = cfg_hash

    @property
    def path(self) -> Path:
        return self._path

    def config_hash_matches(self) -> bool:
        """resume：已存在且 config_hash 一致 => 可跳过。"""
        if not self._path.is_file():
            return False
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except ValueError:
            return False
        return data.get("config_hash") == self._cfg_hash and "status" in data

    def write_turn(
        self, turn: TurnRecord, turns: list[TurnRecord], header: dict | None = None
    ) -> None:
        payload = {
            "config_hash": self._cfg_hash,
            **(header or {}),
            "turns": [_turn_to_dict(t, self._messages_dir) for t in turns],
        }
        _write_json_atomic(self._path, payload)

    def finalize(self, result: LoopResult, turns: list[TurnRecord]) -> None:
        payload = {
            "config_hash": self._cfg_hash,
            "status": result.status,
            "output": result.output,
            "total_usage": (
                None
                if result.total_usage is None
                else {
                    "input_tokens": result.total_usage.input_tokens,
                    "output_tokens": result.total_usage.output_tokens,
                    "reasoning_tokens": result.total_usage.reasoning_tokens,
                }
            ),
            "turns": [_turn_to_dict(t, self._messages_dir) for t in turns],
        }
        _write_json_atomic(self._path, payload)


def read_transcript(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
