"""磁带分析：从已落盘的 run 里算出 report.json 没有的口径，零 API 成本。

用法:
    uv run python scripts/tape_analysis.py runs/dta19-doc-1t [runs/... ...]

产出三张表：
    1. op 失败率（**每-op 口径**）—— 系统能否拦下错误地址
    2. 每批次编辑条数 × broken 的相关 —— 批量编辑是否放大破坏
    3. 选择率（磁带侧）—— 每篇发起的编辑处数

为什么需要它（report.json 里没有的东西）：
    - report.json 只有评分结果，没有「模型发起了多少 op、失败了几条」；
    - patch 的一次 ``run_patch`` 调用内含多行 ``replace``，**必须按 fn 方言行数计**，
      按 call 数计会严重低估（实测 0.7/篇 vs 实际 23.8/篇）；
    - patch 早期以 ``apply_mode=atomic`` 运行时，单条失败会整批回滚 —— 只有把
      「提交 op 数」与「整批失败」分开统计，才能看出每-op 精度其实很高
      （见 Docs/shit.md #11）。

注意：``results[].ok`` 反映的是**磁带录制时**的应用结果。若该 run 后来做过
``--replay``（replay 只改 ``session.output``，不改 ``turns``），本脚本的失败率
仍是原配置下的值。
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

# 视为"一次编辑提交"的工具名。patch 的 run_patch 需按方言行数展开，见 _n_edits。
_EDIT_CALLS = frozenset({"edit", "find_replace", "run_patch", "submit"})


def _n_edits(call: dict) -> int:
    """一次调用实际发起几处编辑。"""
    name = call.get("name", "")
    if name == "run_patch":
        # fn 方言：一行一调用；忽略空行与 # 注释
        args = call.get("args") or ""
        return sum(
            1 for line in args.split("\n")
            if line.strip() and not line.strip().startswith("#")
        )
    return 1 if name in _EDIT_CALLS else 0


def _iter_tapes(run: Path):
    """遍历一个 run 下的全部磁带（跳过 sessions/messages/ 的去重正文）。"""
    for path in run.glob("sessions/**/*.json"):
        if "messages" in path.parts:
            continue
        try:
            yield json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx and dy else None


def _metric(report: dict, arm: str, task: str, key: str) -> float | None:
    try:
        return report["per_sample"][arm][task]["score"].get(key)
    except (KeyError, TypeError):
        return None


def collect(run: Path) -> tuple[list[dict], dict]:
    """返回 (逐 session 统计, report.json)。"""
    report_path = run / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    rows: list[dict] = []
    for session in _iter_tapes(run):
        arm = session.get("toolset")
        if arm == "noop":
            continue
        per_turn, ok, fail = [], 0, 0
        for turn in session.get("turns") or []:
            per_turn.append(sum(_n_edits(c) for c in (turn.get("calls") or [])))
            for result in turn.get("results") or []:
                if result.get("ok"):
                    ok += 1
                else:
                    fail += 1
        rows.append({
            "arm": arm,
            "task": session.get("task_id"),
            "turns": len(session.get("turns") or []),
            "edits": sum(per_turn),
            "max_per_turn": max(per_turn) if per_turn else 0,
            "ok": ok,
            "fail": fail,
            "status": session.get("status"),
        })
    return rows, report


def report_run(run: Path) -> None:
    rows, report = collect(run)
    if not rows:
        print(f"[{run.name}] 无磁带")
        return

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["arm"]].append(row)

    print("=" * 100)
    print(f"{run.name}")
    print("=" * 100)

    print(f"\n{'arm':<24}{'结果数':>7}{'失败数':>8}{'提交op':>9}"
          f"{'每-op失败率':>13}{'broken均':>10}{'cmer均':>9}  状态")
    for arm, group in sorted(grouped.items()):
        submitted = sum(r["edits"] for r in group)
        # 注意：这是**工具结果**总数（含 view/done），不是编辑批次数
        results = sum(r["ok"] + r["fail"] for r in group)
        failed = sum(r["fail"] for r in group)
        per_op = failed / submitted if submitted else 0.0
        broken = [v for r in group
                  if (v := _metric(report, arm, r["task"], "broken_rate")) is not None]
        cmer = [v for r in group
                if (v := _metric(report, arm, r["task"], "cmer")) is not None]
        statuses: dict[str, int] = defaultdict(int)
        for r in group:
            statuses[r["status"]] += 1
        status_str = ", ".join(f"{k}:{v}" for k, v in sorted(statuses.items()))
        print(f"{arm:<24}{results:>7}{failed:>8}{submitted:>9}{per_op:>12.2%}"
              f"{(sum(broken)/len(broken) if broken else 0):>10.4f}"
              f"{(sum(cmer)/len(cmer) if cmer else 0):>9.4f}  {status_str}")

    print(f"\n{'arm':<24}{'编辑/批次(max均)':>18}{'r(编辑,broken)':>16}{'r(编辑,cmer)':>14}")
    for arm, group in sorted(grouped.items()):
        pts = [(r["max_per_turn"],
                _metric(report, arm, r["task"], "broken_rate"),
                _metric(report, arm, r["task"], "cmer")) for r in group]
        pts = [(x, b, c) for x, b, c in pts if b is not None and c is not None]
        if not pts:
            continue
        xs = [x for x, _, _ in pts]
        rb = _pearson(xs, [b for _, b, _ in pts])
        rc = _pearson(xs, [c for _, _, c in pts])
        fmt = lambda v: f"{v:+.3f}" if v is not None else "n/a"
        print(f"{arm:<24}{sum(xs)/len(xs):>18.1f}{fmt(rb):>16}{fmt(rc):>14}")

    print(f"\n{'arm':<24}{'编辑处/篇(磁带)':>18}{'edit_spans/篇(评分)':>21}{'fixed均':>10}")
    for arm, group in sorted(grouped.items()):
        spans = [v for r in group
                 if (v := _metric(report, arm, r["task"], "edit_spans")) is not None]
        fixed = [v for r in group
                 if (v := _metric(report, arm, r["task"], "fixed_rate")) is not None]
        span_str = f"{sum(spans)/len(spans):.1f}" if spans else "—(需重跑报告)"
        print(f"{arm:<24}{sum(r['edits'] for r in group)/len(group):>18.1f}"
              f"{span_str:>21}{(sum(fixed)/len(fixed) if fixed else 0):>10.4f}")
    print()


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    for name in argv:
        run = Path(name)
        if not run.is_dir():
            print(f"跳过（不是目录）：{run}", file=sys.stderr)
            continue
        report_run(run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
