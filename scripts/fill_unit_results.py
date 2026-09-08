"""把 runs/<单元>/report.json 的指标填进 Docs/Experiments/units/<单元>.md 的结果表。

用法:
    uv run python scripts/fill_unit_results.py                    # 全部单元
    uv run python scripts/fill_unit_results.py <单元名> [...]      # 指定单元

只替换 `## 结果` 与 `## 解读` 之间的**表格**，表格前后的说明文字（含跑前写下的
预期）原样保留 —— 预期要留着跟结果对账。

口径：cmer 主报中位数（均值在本任务上被重尾污染，见 Docs/shit.md #14），
max 单列。
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNITS = ROOT / "Docs" / "Experiments" / "units"

COLUMNS = "| arm | cmer 中位 ↓ | max | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | key_leak | out tok | status |"
SEPARATOR = "|---|---|---|---|---|---|---|---|---|---|"


def _fmt(v: float | None, pct: bool = False, digits: int = 4) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.2f}%" if pct else f"{v:.{digits}f}"


def _tokens(agg: dict) -> str:
    tk = agg.get("tokens")
    if not tk:
        return "—"
    out = tk["output"]
    s = f"{out / 1_000_000:.2f}M" if out >= 1_000_000 else f"{out / 1000:.0f}k"
    share = tk.get("reasoning_share")
    return f"{s} ({share * 100:.0f}%r)" if share is not None else s


def _status(report: dict, arm: str) -> str:
    rows = (report.get("per_sample") or {}).get(arm) or {}
    counts = Counter(r.get("status", "?") for r in rows.values())
    if list(counts) == ["done"]:
        return f"done {counts['done']}"
    return ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))


def build_table(report: dict) -> str:
    lines = [COLUMNS, SEPARATOR]
    for arm, agg in report["aggregate"].items():
        c = agg.get("cmer") or {}
        g = lambda k: (agg.get(k) or {}).get("mean")
        lines.append(
            f"| `{arm}` | **{_fmt(c.get('median'))}** | {_fmt(c.get('max'))} "
            f"| {_fmt(g('fixed_rate'), pct=True)} | {_fmt(g('broken_rate'), pct=True)} "
            f"| {_fmt(g('halluc_ins'), pct=True)} | {_fmt(g('edit_spans'), digits=1)} "
            f"| {_fmt(g('key_leak'), pct=True)} | {_tokens(agg)} | {_status(report, arm)} |"
        )
    return "\n".join(lines)


def fill(unit: str) -> str:
    doc = UNITS / f"{unit}.md"
    report_path = ROOT / "runs" / unit / "report.json"
    if not doc.exists():
        return f"跳过 {unit}：无文档"
    if not report_path.exists():
        return f"跳过 {unit}：无 report.json"

    report = json.loads(report_path.read_text(encoding="utf-8"))
    text = doc.read_text(encoding="utf-8")
    start = text.index("## 结果")
    end = text.index("## 解读", start)
    section = text[start:end]

    # 表格 = 表头行起、到最后一个以 | 开头的行止；其余文字原样保留
    body = section.splitlines()
    head = next(i for i, l in enumerate(body) if l.startswith("| arm |"))
    tail = head
    while tail + 1 < len(body) and body[tail + 1].startswith("|"):
        tail += 1
    body[head : tail + 1] = build_table(report).splitlines()

    new_section = "\n".join(body)
    new_section = new_section.replace("<跑完填>\n\n", "").replace("<跑完填>", "")
    doc.write_text(text[:start] + new_section + text[end:], encoding="utf-8")
    return f"✅ {unit}"


def main(argv: list[str]) -> int:
    names = argv or sorted(
        p.stem for p in UNITS.glob("*.md") if not p.stem.startswith("_")
    )
    for name in names:
        print(fill(name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
