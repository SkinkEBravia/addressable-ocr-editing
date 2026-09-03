"""experiment 的磁带存储：Session <-> runs/<name>/sessions/ 下的 JSON。

对应 Docs/Design/11-experiment.md「磁带存储」节。

- 逐轮增量落盘：每次写 = 全量原子重写该 cell 的磁带。
- 请求 messages 全文按内容哈希去重存放于 sessions/messages/。
- resume 判定：磁带存在 + config_hash 一致 + 终态为 done / budget_exceeded；
  failed:* 与 running（中断残留）一律重跑。
- 磁带是不可再生资产：任何清理操作不得删 sessions/。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from agent import TAPE_VERSION, Budget, Session, ToolCall, ToolResult, Turn
from llm import Completion, Failure, Message, Usage

__all__ = ["SessionStore"]


def _write_json_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


class SessionStore:
    """一个运行目录下的磁带存取。无内部状态，跨线程共享安全（原子写）。"""

    def __init__(self, out: Path) -> None:
        self._root = Path(out) / "sessions"
        self._messages_dir = self._root / "messages"

    # -- 序列化 -----------------------------------------------------------

    def _messages_ref(self, messages: tuple[Message, ...]) -> str:
        """messages 全文按内容哈希去重存放，返回引用。"""
        payload = [{"role": m.role, "content": m.content} for m in messages]
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        path = self._messages_dir / f"{digest}.json"
        if not path.exists():
            _write_json_atomic(path, payload)
        return f"sha256:{digest}"

    def _load_messages(self, ref: str) -> tuple[Message, ...]:
        digest = ref.removeprefix("sha256:")
        payload = json.loads(
            (self._messages_dir / f"{digest}.json").read_text(encoding="utf-8")
        )
        return tuple(Message(m["role"], m["content"]) for m in payload)

    def _turn_to_dict(self, turn: Turn) -> dict:
        completion = turn.completion
        return {
            "index": turn.index,
            "messages_ref": self._messages_ref(turn.request),
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
                "elapsed_s": completion.elapsed_s,
            },
            "calls": [{"name": c.name, "args": c.args_text} for c in turn.calls],
            "results": [{"ok": r.ok, "feedback": r.feedback} for r in turn.results],
            "parse_error": turn.parse_error,
        }

    def _turn_from_dict(self, d: dict) -> Turn:
        u = d["completion"].get("usage")
        return Turn(
            index=int(d["index"]),
            request=self._load_messages(d["messages_ref"]),
            completion=Completion(
                text=d["completion"]["text"],
                usage=(
                    None
                    if u is None
                    else Usage(u["input_tokens"], u["output_tokens"],
                               u.get("reasoning_tokens"))
                ),
                raw=d["completion"].get("raw"),
                elapsed_s=d["completion"].get("elapsed_s"),
            ),
            calls=tuple(ToolCall(c["name"], c.get("args", "")) for c in d.get("calls", [])),
            results=tuple(
                ToolResult(bool(r["ok"]), str(r["feedback"])) for r in d.get("results", [])
            ),
            parse_error=d.get("parse_error"),
        )

    # -- 存取 -------------------------------------------------------------

    def path_for(self, task_id: str, toolset: str) -> Path:
        return self._root / task_id / f"{toolset}.json"

    def write(self, session: Session) -> None:
        """全量原子重写该 cell 的磁带（每轮调用即增量落盘）。"""
        payload = {
            "version": TAPE_VERSION,
            "task_id": session.task_id,
            "toolset": session.toolset,
            "config_hash": session.config_hash,
            "budget": {
                "max_turns": session.budget.max_turns,
                "token_budget": session.budget.token_budget,
            },
            "status": session.status,
            "failure": None if session.failure is None else session.failure.to_dict(),
            "output": session.output,
            "turns": [self._turn_to_dict(t) for t in session.turns],
        }
        _write_json_atomic(self.path_for(session.task_id, session.toolset), payload)

    def read(self, task_id: str, toolset: str) -> Session | None:
        """读回磁带；不存在或损坏返回 None。tool_state 为空（replay 自行重建）。"""
        path = self.path_for(task_id, toolset)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None
        version = int(data.get("version", 0))
        if version != TAPE_VERSION:
            return None  # 旧格式磁带不解释，视为不存在（重跑）
        b = data.get("budget") or {}
        failure = data.get("failure")
        return Session(
            task_id=str(data["task_id"]),
            toolset=str(data["toolset"]),
            config_hash=str(data.get("config_hash", "")),
            budget=Budget(
                max_turns=int(b.get("max_turns", 1)),
                token_budget=b.get("token_budget"),
            ),
            turns=[self._turn_from_dict(t) for t in data.get("turns", [])],
            status=str(data.get("status", "running")),
            failure=None if failure is None else Failure.from_dict(failure),
            output=data.get("output"),
        )

    def resumable(self, task_id: str, toolset: str, config_hash: str) -> Session | None:
        """可 resume 则返回磁带 Session，否则 None。

        完成态 = done / budget_exceeded；failed:* 与 running（中断残留）重跑。
        """
        session = self.read(task_id, toolset)
        if session is None:
            return None
        if session.config_hash != config_hash:
            return None
        if session.status not in ("done", "budget_exceeded"):
            return None
        return session
