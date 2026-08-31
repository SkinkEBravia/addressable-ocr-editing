"""application CLI 的测试。

覆盖（对应 Docs/Design/07-agent-api.md「CLI 对方言的限制」与「验收」）：

- ingest -> view -> patch -> write 全流程
- 端到端等式：ingest 后直接 write 逐字节等于原文件（含 BOM / 无尾随换行）
- patch 失败的退出码（1 解析 / 2 降解 / 3 apply / 4 I/O）与 store 不变
- rollback 后 view 内容回退
- ``-f json`` 输出可被 json.loads
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import ir
from application import main

TEXT = "hello world, 你好世界"  # 17 chars；size=4 -> b1..b5


def _ingest(src: Path, session: Path, size: int = 4) -> int:
    return main(["ingest", str(src), "--session", str(session), "--size", str(size)])


def _patch_stdin(monkeypatch, text: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


def _snapshot_id_from(capsys) -> str:
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if ln.startswith("snapshot: "))
    return line.split(": ", 1)[1]


def _store_fingerprint(session: Path) -> tuple[str, dict[str, str]]:
    store = ir.Store(session)
    files = {
        str(p.relative_to(session)): p.read_text(encoding="utf-8")
        for p in sorted(session.rglob("*"))
        if p.is_file()
    }
    return ir.current(store), files


class TestFullFlow:
    def test_ingest_view_patch_write(self, tmp_path, capsys, monkeypatch) -> None:
        src = tmp_path / "doc.txt"
        src.write_bytes(TEXT.encode("utf-8"))
        session = tmp_path / "session"

        assert _ingest(src, session) == 0
        out = capsys.readouterr().out
        assert out.startswith("snapshot: s-")
        assert "blocks: 5" in out
        # 会话目录初始化：store 结构 + session.json 记录原文件绝对路径
        assert (session / "current").exists()
        meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
        assert meta["source_path"] == str(src.resolve())

        assert main(["view", "--session", str(session)]) == 0
        payload = capsys.readouterr().out
        assert '<x id="b1"\\>\nhell\n</x>\n' in payload
        assert '<x id="b5"\\>' in payload

        _patch_stdin(monkeypatch, 'set_content(b2, "REPLACED")')
        assert main(["patch", "--session", str(session)]) == 0
        out = capsys.readouterr().out
        assert "[updated] b2" in out
        assert '<x id="b2"\\>\nREPLACED\n</x>\n' in out

        out_file = tmp_path / "out.txt"
        assert main(["write", "--session", str(session), "-o", str(out_file)]) == 0
        assert out_file.read_bytes() == (TEXT[:4] + "REPLACED" + TEXT[8:]).encode("utf-8")


class TestByteEquality:
    @pytest.mark.parametrize(
        "raw",
        [
            "纯文本，没有尾随换行".encode("utf-8"),
            b"\xef\xbb\xbf" + "带 utf-8 BOM 的内容\n第二行\n".encode("utf-8"),
            "".encode("utf-8"),  # 空文件
        ],
    )
    def test_ingest_then_write_is_byte_identical(
        self, tmp_path, capsys, raw: bytes
    ) -> None:
        src = tmp_path / "doc.txt"
        src.write_bytes(raw)
        session = tmp_path / "session"
        assert _ingest(src, session) == 0
        capsys.readouterr()
        # 缺省写回原文件路径（session.json 记录）
        assert main(["write", "--session", str(session)]) == 0
        assert src.read_bytes() == raw

    def test_write_without_recorded_source_requires_output(
        self, tmp_path, capsys
    ) -> None:
        src = tmp_path / "doc.txt"
        src.write_bytes(TEXT.encode("utf-8"))
        session = tmp_path / "session"
        assert _ingest(src, session) == 0
        (session / "session.json").unlink()  # 会话元数据缺失
        capsys.readouterr()
        assert main(["write", "--session", str(session)]) == 4


class TestPatchFailures:
    def test_parse_error_exit_1(self, tmp_path, capsys, monkeypatch) -> None:
        src = tmp_path / "doc.txt"
        src.write_bytes(TEXT.encode("utf-8"))
        session = tmp_path / "session"
        assert _ingest(src, session) == 0
        before = _store_fingerprint(session)
        capsys.readouterr()

        _patch_stdin(monkeypatch, "remove(b1)\nthis is broken")
        assert main(["patch", "--session", str(session)]) == 1
        err = capsys.readouterr().err
        assert "line 2" in err
        assert _store_fingerprint(session) == before

    def test_degrade_error_exit_2(self, tmp_path, capsys, monkeypatch) -> None:
        src = tmp_path / "doc.txt"
        src.write_bytes(TEXT.encode("utf-8"))
        session = tmp_path / "session"
        assert _ingest(src, session) == 0
        before = _store_fingerprint(session)
        capsys.readouterr()

        _patch_stdin(monkeypatch, "remove(b99)")
        assert main(["patch", "--session", str(session)]) == 2
        err = capsys.readouterr().err
        assert "line 1" in err and "b99" in err
        assert _store_fingerprint(session) == before

    def test_apply_error_exit_3(self, tmp_path, capsys, monkeypatch) -> None:
        src = tmp_path / "doc.txt"
        src.write_bytes(TEXT.encode("utf-8"))
        session = tmp_path / "session"
        assert _ingest(src, session) == 0
        before = _store_fingerprint(session)
        capsys.readouterr()

        _patch_stdin(monkeypatch, "remove(b1)\nremove(b1)")
        assert main(["patch", "--session", str(session)]) == 3
        err = capsys.readouterr().err
        assert "line 2" in err and "KEY_NOT_FOUND" in err
        assert _store_fingerprint(session) == before


class TestIOFailures:
    def test_ingest_missing_file_exit_4(self, tmp_path, capsys) -> None:
        assert main(["ingest", str(tmp_path / "nope.txt"),
                     "--session", str(tmp_path / "s")]) == 4
        assert "error" in capsys.readouterr().err

    def test_ingest_undecodable_file_exit_4(self, tmp_path, capsys) -> None:
        src = tmp_path / "bad.txt"
        src.write_bytes(b"\xff\xfe\xfd")  # utf-16-le BOM + 奇数字节
        assert main(["ingest", str(src), "--session", str(tmp_path / "s")]) == 4

    def test_view_without_session_exit_4(self, tmp_path, capsys) -> None:
        assert main(["view", "--session", str(tmp_path / "empty")]) == 4
        assert "error" in capsys.readouterr().err

    def test_rollback_unknown_snapshot_exit_4(self, tmp_path, capsys) -> None:
        src = tmp_path / "doc.txt"
        src.write_bytes(TEXT.encode("utf-8"))
        session = tmp_path / "session"
        assert _ingest(src, session) == 0
        capsys.readouterr()
        assert main(["rollback", "s-nonexistent", "--session", str(session)]) == 4

    def test_unsupported_partition_rejected(self, tmp_path) -> None:
        src = tmp_path / "doc.txt"
        src.write_bytes(TEXT.encode("utf-8"))
        with pytest.raises(SystemExit):  # argparse 用法错误（--partition 仅支持 chars）
            main(["ingest", str(src), "--session", str(tmp_path / "s"),
                  "--partition", "md"])


class TestRollback:
    def test_rollback_restores_view(self, tmp_path, capsys, monkeypatch) -> None:
        src = tmp_path / "doc.txt"
        src.write_bytes(TEXT.encode("utf-8"))
        session = tmp_path / "session"
        assert _ingest(src, session) == 0
        first_id = _snapshot_id_from(capsys)

        _patch_stdin(monkeypatch, 'set_content(b1, "XXXX")')
        assert main(["patch", "--session", str(session)]) == 0
        capsys.readouterr()

        assert main(["rollback", first_id, "--session", str(session)]) == 0
        assert ir.current(ir.Store(session)) == first_id
        assert main(["view", "--session", str(session)]) == 0
        payload = capsys.readouterr().out
        assert '<x id="b1"\\>\nhell\n</x>\n' in payload  # 内容回退
        assert "XXXX" not in payload


class TestJsonFormat:
    def test_patch_success_json(self, tmp_path, capsys, monkeypatch) -> None:
        src = tmp_path / "doc.txt"
        src.write_bytes(TEXT.encode("utf-8"))
        session = tmp_path / "session"
        assert _ingest(src, session) == 0
        capsys.readouterr()

        _patch_stdin(monkeypatch, 'append(b5, "TAIL", {"kind": "end"})')
        assert main(["patch", "--session", str(session), "-f", "json"]) == 0
        data = json.loads(capsys.readouterr().out)  # 可被 json.loads
        assert data["snapshot_id"].startswith("s-")
        (ab,) = data["affected"]
        assert ab["key"] == "b6" and ab["status"] == "appended"
        assert ab["annotated"] == '<x id="b6"\\>\nTAIL\n</x>\n'

    def test_patch_failure_json(self, tmp_path, capsys, monkeypatch) -> None:
        src = tmp_path / "doc.txt"
        src.write_bytes(TEXT.encode("utf-8"))
        session = tmp_path / "session"
        assert _ingest(src, session) == 0
        capsys.readouterr()

        _patch_stdin(monkeypatch, "remove(b1)\nremove(b1)")
        assert main(["patch", "--session", str(session), "-f", "json"]) == 3
        data = json.loads(capsys.readouterr().out)
        assert data["error"] == "surface"
        assert data["stage"] == "apply"
        assert data["surface_index"] == 1
        assert data["position"] == [2, 2]
        assert data["cause"] == "KEY_NOT_FOUND"

    def test_parse_failure_json(self, tmp_path, capsys, monkeypatch) -> None:
        src = tmp_path / "doc.txt"
        src.write_bytes(TEXT.encode("utf-8"))
        session = tmp_path / "session"
        assert _ingest(src, session) == 0
        capsys.readouterr()

        _patch_stdin(monkeypatch, "not a call")
        assert main(["patch", "--session", str(session), "-f", "json"]) == 1
        data = json.loads(capsys.readouterr().out)
        assert data["error"] == "parse" and data["line"] == 1
