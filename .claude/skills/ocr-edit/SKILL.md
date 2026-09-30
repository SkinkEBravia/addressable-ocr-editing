---
name: ocr-edit
description: Use when asked to correct, fix, or edit OCR text in a file with this repo's block-addressed CLI (`python -m application`), e.g. "fix the OCR errors in X.txt", "patch this OCR file", "correct OCR text and write it to Y". Covers ingest, view, patch, write, rollback via `uv run`.
---

# OCR edit via `uv run python -m application`

Edit a text file as addressable blocks. The file is never touched until `write`.

Run every command from the repo root (where `pyproject.toml` is). The prefix is always:

```bash
uv run python -m application <command> ...
```

## Workflow

1. **Ingest** – splits the file into blocks and creates a session dir (outside git-tracked paths, e.g. a temp dir):
   `uv run python -m application ingest <file> --session <dir>`
   Prints `snapshot: <id>` and `blocks: <n>`.
2. **View** – prints every block as `<x id="b1"\>` ... `</x>`. Block ids come from here only:
   `uv run python -m application view --session <dir>`
3. **Patch** – patch text goes in via **stdin**, never argv. Use a quoted heredoc:
   ```bash
   uv run python -m application patch --session <dir> -f json <<'EOF'
   replace(b1, "teh", "the")
   replace(b3, "rn", "m")
   EOF
   ```
   On success it prints the new `snapshot_id` and the affected blocks re-rendered; read them to confirm the edit.
4. **Repeat** view/patch until the text is clean.
5. **Write** – always with `-o`, to a path different from the input (see Rules):
   `uv run python -m application write --session <dir> -o <out-file>`

## Patch language (one call per line)

`replace(id, old, new)` · `set_content(id, text)` · `append(anchor, text)` · `remove(id)` · `merge(a, b)` · `move(id, anchor)`

- Args are positional. Strings use JSON syntax: escape `"` and `\`, write newlines as `\n`. Ids may be bare (`b3`) or quoted.
- Prefer `replace` for OCR fixes. It replaces **every** occurrence of `old` inside that block; add surrounding context to `old` when only one should change.
- Use `set_content` only when a block needs rewriting wholesale. Avoid `move`/`merge` (they change block identity).
- Ids refer to the view **before** the patch. A patch cannot reference blocks it creates.
- Lines starting with `#` and blank lines are ignored.

## Rules

- **Never overwrite the input file.** `write` without `-o` overwrites it, and `-o <input path>` does the same. The `-o` path must differ from the input path. If the user gave no output path, write to `<stem>.fixed<ext>` next to the input and report that path. Overwrite only if the user says so explicitly (e.g. "in place", "overwrite").
- Look at `view` before patching; do not guess ids (they start at `b1`, not `b0`).
- A patch is atomic: if any line fails, nothing is applied and the session is unchanged. Fix the failing line and resend.
- Run commands one at a time. There is no locking.
- Do not edit the source file directly; go through the session.

## Errors and exit codes

Use `-f json` on `patch` for machine-readable errors (`stage`, `surface_index`, `position` = patch line, `message`).

| Exit | Meaning | Usual fix |
|---|---|---|
| 0 | ok | – |
| 1 | patch syntax error | fix quoting/JSON escaping on the reported line |
| 2 | unknown id, or `old` not found in block | re-run `view`; copy `old` exactly from the block |
| 3 | apply failed | read `cause` in the JSON |
| 4 | I/O or session error | check paths and `--session` |

## Undo

Each `ingest`/`patch` prints a snapshot id. `uv run python -m application rollback <snapshot_id> --session <dir>` moves the session back to it; then `write` again if needed.
