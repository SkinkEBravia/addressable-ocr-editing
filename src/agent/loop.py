"""agent 的 loop：驱动 Session 的引擎。

对应 Docs/Design/09-tools.md「Loop」节。

- 轮内：complete -> parse -> 按序 invoke -> feedback 回灌下一轮；Done -> 结束。
- 三通道：ToolParseError / ToolResult(ok=False) 进对话；LLMError 记 failure
  终止；invoke 的意外异常记 Failure(stage="tool") 终止（我们的 bug 不喂模型）。
- 每轮完成即 on_turn(session) 回调（experiment 借此增量落盘）。
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from pathlib import Path

from agent.assembly import build_initial_messages
from agent.session import Session, Turn
from agent.toolset import Budget, Done, ToolParseError, ToolSet
from llm import Failure, LLMClient, LLMError, Message

__all__ = ["start_session", "run_session"]

logger = logging.getLogger("agent.loop")

_TRACEBACK_TAIL = 2000
_LOG_EVERY_N_CALLS = 50  # 大批量调用时每隔 N 条报一次执行进度


def start_session(
    toolset: ToolSet,
    *,
    label: str,
    task_id: str,
    task_input: str,
    task_meta: dict,
    instruction: str,
    workdir: Path,
    config_hash: str,
    budget: Budget,
) -> tuple[Session, list[Message]]:
    """组装阶段：构造 tool_state + Session + 初始 messages。

    组装期异常（IR 初始化等）记 Failure(stage="tool", kind="tool_init")，
    返回的 Session 已是失败终态，run_session 会直接收束。
    """
    workdir.mkdir(parents=True, exist_ok=True)
    session = Session(
        task_id=task_id,
        toolset=label,
        config_hash=config_hash,
        budget=budget,
    )
    try:
        session.tool_state = toolset.make_tool_state(task_input, task_meta, workdir)
        presented = toolset.present_input(task_input, session.tool_state)
    except Exception as exc:  # 组装失败：失败通道
        session.failure = Failure(
            stage="tool",
            kind="tool_init",
            message=f"{type(exc).__name__}: {exc}",
            detail={"traceback": traceback.format_exc()[-_TRACEBACK_TAIL:]},
        )
        session.status = "failed:tool_init"
        session.output = task_input
        return session, []
    messages = build_initial_messages(
        instruction, toolset.prompt_clause, presented, task_meta
    )
    return session, messages


def run_session(
    client: LLMClient,
    toolset: ToolSet,
    session: Session,
    messages: list[Message],
    *,
    fallback_text: str,
    on_turn: Callable[[Session], None] | None = None,
    on_delta: Callable[[str], None] | None = None,
    on_activity: Callable[[str], None] | None = None,
) -> Session:
    """多轮 agent loop；就地推进 session 并返回它。

    fallback_text = 失败时的回退产出（原文）。
    on_activity：阶段可观测回调（LLM 请求中 / 执行 i/N / 收尾），
    experiment 借此驱动进度显示的活动行；纯观察，不影响语义。
    """
    if session.failure is not None:  # 组装期已失败
        return session

    label = f"{session.task_id} × {session.toolset}"

    def activity(msg: str) -> None:
        if on_activity is not None:
            on_activity(f"{label} | {msg}")

    if not toolset.uses_llm:  # noop：零轮迭代
        session.status = "done"
        _finish_with_extract(toolset, session, fallback_text)
        return session

    def flush_state() -> None:
        """轮末持久化钩子：工具集实现了 flush 才调用（见 09 工具契约）。"""
        flush = getattr(toolset, "flush", None)
        if flush is not None:
            flush(session.tool_state)

    done = False
    while len(session.turns) < session.budget.max_turns:
        index = len(session.turns)
        activity(f"第 {index + 1} 轮：LLM 请求中")
        try:
            completion = client.complete(messages, on_delta=on_delta)
        except LLMError as exc:  # 失败通道
            session.failure = exc.failure
            session.status = f"failed:{exc.kind}"
            session.output = fallback_text
            return session
        request = tuple(messages)
        messages.append(Message("assistant", completion.text))

        try:
            outcome = toolset.parse(completion.text)
        except ToolParseError as exc:  # 对话通道
            logger.info(
                "task=%s toolset=%s turn=%d parse error: %s",
                session.task_id, session.toolset, index, exc,
            )
            activity(f"第 {index + 1} 轮：parse error，回灌对话")
            session.turns.append(Turn(index, request, completion, parse_error=str(exc)))
            if on_turn is not None:
                on_turn(session)
            messages.append(Message("user", f"parse error: {exc}"))
            continue

        if isinstance(outcome, Done):
            activity(f"第 {index + 1} 轮：done，收尾")
            try:
                flush_state()
            except Exception as exc:  # 落盘失败 = 环境问题：失败通道
                session.turns.append(Turn(index, request, completion))
                session.failure = Failure(
                    stage="tool",
                    kind="tool_persist",
                    message=f"{type(exc).__name__}: {exc}",
                    detail={"traceback": traceback.format_exc()[-_TRACEBACK_TAIL:]},
                )
                session.status = "failed:tool_persist"
                session.output = fallback_text
                if on_turn is not None:
                    on_turn(session)
                return session
            session.turns.append(Turn(index, request, completion))
            if on_turn is not None:
                on_turn(session)
            done = True
            break

        results = []
        finish = False
        n_calls = len(outcome)
        if n_calls:
            logger.info(
                "task=%s toolset=%s turn=%d 解析出 %d 条调用，开始逐条执行",
                session.task_id, session.toolset, index, n_calls,
            )
            activity(f"第 {index + 1} 轮：执行 {n_calls} 条调用")
        for i, call in enumerate(outcome):  # 同轮多调用按序，后续看到前面结果
            try:
                result = toolset.invoke(call, session.tool_state)
            except Exception as exc:  # 意外异常 = 我们的 bug：失败通道
                try:
                    flush_state()
                except Exception:
                    logger.exception("task=%s 失败后 flush 也失败", session.task_id)
                session.turns.append(
                    Turn(index, request, completion, tuple(outcome[: len(results)]),
                         tuple(results))
                )
                session.failure = Failure(
                    stage="tool",
                    kind="tool_error",
                    message=f"{type(exc).__name__}: {exc}",
                    detail={"traceback": traceback.format_exc()[-_TRACEBACK_TAIL:]},
                )
                session.status = "failed:tool_error"
                session.output = fallback_text
                if on_turn is not None:
                    on_turn(session)
                return session
            results.append(result)
            finish = finish or result.finish
            if (i + 1) % _LOG_EVERY_N_CALLS == 0:
                logger.info(
                    "task=%s toolset=%s turn=%d 已执行 %d/%d 条调用",
                    session.task_id, session.toolset, index, i + 1, n_calls,
                )
                activity(f"第 {index + 1} 轮：执行 {i + 1}/{n_calls} 条调用")
        try:
            flush_state()
        except Exception as exc:  # 落盘失败 = 环境问题：失败通道
            session.turns.append(
                Turn(index, request, completion, tuple(outcome), tuple(results))
            )
            session.failure = Failure(
                stage="tool",
                kind="tool_persist",
                message=f"{type(exc).__name__}: {exc}",
                detail={"traceback": traceback.format_exc()[-_TRACEBACK_TAIL:]},
            )
            session.status = "failed:tool_persist"
            session.output = fallback_text
            if on_turn is not None:
                on_turn(session)
            return session
        session.turns.append(
            Turn(index, request, completion, tuple(outcome), tuple(results))
        )
        if on_turn is not None:
            on_turn(session)
        if finish:  # 工具侧宣告完成（如顺序任务处理完最后一个单元）
            done = True
            break
        feedbacks = [r.feedback if r.ok else f"error: {r.feedback}" for r in results]
        messages.append(Message("user", "\n".join(feedbacks)))

        usage = session.usage
        if (
            session.budget.token_budget is not None
            and usage is not None
            and usage.total > session.budget.token_budget
        ):
            break

    activity("收尾（extract）")
    session.status = "done" if done else "budget_exceeded"
    _finish_with_extract(toolset, session, fallback_text)
    return session


def _finish_with_extract(
    toolset: ToolSet, session: Session, fallback_text: str
) -> None:
    """工具应用出口：extract -> session.output；失败回退原文。"""
    try:
        session.output = toolset.extract(session.tool_state, session).text
    except Exception as exc:  # 失败通道
        session.failure = Failure(
            stage="extract",
            kind="extract_error",
            message=f"{type(exc).__name__}: {exc}",
            detail={"traceback": traceback.format_exc()[-_TRACEBACK_TAIL:]},
        )
        session.status = "failed:extract_error"
        session.output = fallback_text
