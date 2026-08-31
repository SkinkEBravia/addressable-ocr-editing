"""prompts：模板加载与渲染。

模板文件在 ``prompts/`` 目录（``blocr_rewrite.md`` / ``blocr_patch.md``），
占位符形如 ``{language}`` / ``{text}`` / ``{view}``。渲染用字面替换
（不用 str.format，避免与模板中 JSON 示例的花括号冲突）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

__all__ = ["load_template", "render_prompt", "render_rewrite_prompt", "render_patch_prompt"]

_PROMPTS_DIR = Path(__file__).parent / "prompts"

REWRITE_TEMPLATE = "blocr_rewrite"
PATCH_TEMPLATE = "blocr_patch"


@lru_cache(maxsize=None)
def load_template(name: str) -> str:
    """按名加载模板文本（不带 .md 后缀）。"""
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


def render_prompt(template: str, **values: str) -> str:
    """字面替换 ``{key}`` 占位符；未提供的占位符保持原样。"""
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)
    return out


def render_rewrite_prompt(language: str, text: str) -> str:
    """blocr 臂（完全重写通道）的 prompt。"""
    return render_prompt(load_template(REWRITE_TEMPLATE), language=language, text=text)


def render_patch_prompt(language: str, view: str) -> str:
    """blocr+system 臂（fn patch 通道）的 prompt；``view`` 为标注后的视图 payload。"""
    return render_prompt(load_template(PATCH_TEMPLATE), language=language, view=view)
