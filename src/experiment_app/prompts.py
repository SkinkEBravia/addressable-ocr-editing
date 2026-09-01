"""prompts：模板加载与渲染。

模板引用（``prompt`` 字段）两种解析：

- 不含 ``/`` / ``\\`` 且不以 ``.md`` 结尾 -> 包内 ``prompts/<name>.md``；
- 否则按相对 TOML 文件所在目录（``base_dir``）的路径解析。

缓存键用解析后的绝对路径。占位符形如 ``{language}`` / ``{text}`` / ``{view}``，
渲染用字面替换（不用 str.format，避免与模板中 JSON 示例的花括号冲突）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

__all__ = [
    "REWRITE_TEMPLATE",
    "PATCH_TEMPLATE",
    "resolve_template_path",
    "load_template",
    "render_prompt",
    "render_rewrite_prompt",
    "render_patch_prompt",
]

_PROMPTS_DIR = Path(__file__).parent / "prompts"

REWRITE_TEMPLATE = "blocr_rewrite"
PATCH_TEMPLATE = "blocr_patch"


def resolve_template_path(prompt: str, base_dir: Path | None = None) -> Path:
    """模板引用 -> 模板文件路径（两种解析，见模块 docstring）。"""
    if "/" not in prompt and "\\" not in prompt and not prompt.endswith(".md"):
        return _PROMPTS_DIR / f"{prompt}.md"
    base = Path(base_dir) if base_dir is not None else Path.cwd()
    return (base / prompt).resolve()


@lru_cache(maxsize=None)
def _load_resolved(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_template(prompt: str, base_dir: Path | None = None) -> str:
    """按引用加载模板文本；缓存键为解析后的绝对路径。"""
    return _load_resolved(str(resolve_template_path(prompt, base_dir)))


def render_prompt(template: str, **values: str) -> str:
    """字面替换 ``{key}`` 占位符；未提供的占位符保持原样。"""
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)
    return out


def render_rewrite_prompt(
    language: str,
    text: str,
    *,
    prompt: str = REWRITE_TEMPLATE,
    base_dir: Path | None = None,
) -> str:
    """rewrite 通道（完全重写）的 prompt。"""
    return render_prompt(load_template(prompt, base_dir), language=language, text=text)


def render_patch_prompt(
    language: str,
    view: str,
    *,
    prompt: str = PATCH_TEMPLATE,
    base_dir: Path | None = None,
) -> str:
    """patch 通道（fn patch）的 prompt；``view`` 为标注后的视图 payload。"""
    return render_prompt(load_template(prompt, base_dir), language=language, view=view)
