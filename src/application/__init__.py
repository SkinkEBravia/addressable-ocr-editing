"""application：装配层 + CLI。

把 sourceio / partition / ir / reconstruction / view / surface 装配成
五个命令（ingest / view / patch / write / rollback），会话目录共享状态。
设计规格见 Docs/Design/07-agent-api.md「CLI」节。

用法::

    uv run python -m application ingest <file> --session <dir> [--size N]
    uv run python -m application view --session <dir>
    uv run python -m application patch --session <dir> [-f json] < patch.txt
    uv run python -m application write --session <dir> [-o <path>]
    uv run python -m application rollback <SnapshotId> --session <dir>
"""

from application.cli import (
    EX_APPLY,
    EX_DEGRADE,
    EX_IO,
    EX_OK,
    EX_PARSE,
    main,
)

__all__ = ["main", "EX_OK", "EX_PARSE", "EX_DEGRADE", "EX_APPLY", "EX_IO"]
