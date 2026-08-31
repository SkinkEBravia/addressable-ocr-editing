"""surface（Agent 操作面）的测试。

对应 Docs/Design/07-agent-api.md 的验收：

- 方言 fn：七种调用解析、字符串转义、attrs JSON、HEAD 锚点、注释与空行、
  各类语法错误抛 ParseError 且行号正确。
- 降解：双射映射、move/merge/replace 展开序列与 origin 溯源、未知 id 与
  replace 的 PATTERN_NOT_FOUND 抛 SurfaceError。
- run_patch：成功路径（受影响块的 status/key/annotated 正确）、apply 失败
  时错误回溯到正确的 surface 行、失败时 store 不变。
"""

from __future__ import annotations

import json

import pytest
import ir
import sourceio
from partition import partition_chars
from surface import (
    PATTERN_NOT_FOUND,
    Append,
    Merge,
    Move,
    ParseError,
    Remove,
    Replace,
    SetAttrs,
    SetContent,
    SurfaceError,
    degrade,
    parse,
    run_patch,
)
from view import blockkey_as_is, present, xml_ish

TEXT = "aaaabbbbccccdddd"  # size=4 -> b1..b4, key_cursor=5


def _snapshot(text: str = TEXT, size: int = 4) -> ir.DocumentSnapshot:
    source = sourceio.decode(text.encode("utf-8"))
    return ir.birth(source, partition_chars(source, size))


def _ref_map(snapshot: ir.DocumentSnapshot):
    return present(snapshot, blockkey_as_is, xml_ish).reference_map


def _store(tmp_path, text: str = TEXT, size: int = 4):
    snapshot = _snapshot(text, size)
    store = ir.Store(tmp_path / "session")
    ir.save(store, snapshot)
    return store, snapshot


def _store_fingerprint(store: ir.Store) -> tuple[str, dict[str, str]]:
    """(current, {相对路径: 文件内容})——用于断言 store 不变。"""
    files = {
        str(p.relative_to(store.root)): p.read_text(encoding="utf-8")
        for p in sorted(store.root.rglob("*"))
        if p.is_file()
    }
    return ir.current(store), files


class TestParse:
    def test_seven_operations(self) -> None:
        ops = parse(
            'set_content(b3, "替换后的全文")\n'
            'set_attrs(b3, {"start": 120})\n'
            'append(b2, "新块内容")\n'
            'append(HEAD, "文首", {"kind": "intro"})\n'
            "remove(b4)\n"
            "move(b1, b5)\n"
            "merge(b1, b2)\n"
            'replace(b3, "teh", "the")\n'
        )
        assert len(ops) == 8
        assert ops[0] == SetContent(position=(1, 1), id="b3", text="替换后的全文")
        assert ops[1] == SetAttrs(position=(2, 2), id="b3", attrs={"start": 120})
        assert ops[2] == Append(position=(3, 3), anchor="b2", text="新块内容", attrs=None)
        assert ops[3] == Append(
            position=(4, 4), anchor="HEAD", text="文首", attrs={"kind": "intro"}
        )
        assert ops[4] == Remove(position=(5, 5), id="b4")
        assert ops[5] == Move(position=(6, 6), id="b1", anchor="b5")
        assert ops[6] == Merge(position=(7, 7), a="b1", b="b2")
        assert ops[7] == Replace(position=(8, 8), id="b3", old="teh", new="the")

    def test_string_escapes(self) -> None:
        (op,) = parse(r'set_content(b1, "a\nb\"c\\de")')
        assert isinstance(op, SetContent)
        assert op.text == 'a\nb"c\\de'

    def test_attrs_json_nested(self) -> None:
        (op,) = parse('set_attrs(b2, {"k": 1, "nested": {"x": [1, 2]}, "f": 1.5, "n": null})')
        assert isinstance(op, SetAttrs)
        assert op.attrs == {"k": 1, "nested": {"x": [1, 2]}, "f": 1.5, "n": None}

    def test_head_anchor_and_default_attrs(self) -> None:
        (op,) = parse('append(HEAD, "文首")')
        assert isinstance(op, Append)
        assert op.anchor == "HEAD"
        assert op.attrs is None

    def test_comments_and_blank_lines_ignored(self) -> None:
        ops = parse("\n# 注释\n   \n  # 前导空白后注释\n\nremove(b1)\n\n")
        assert ops == (Remove(position=(6, 6), id="b1"),)

    def test_whitespace_tolerance(self) -> None:
        (op,) = parse('  append( b1 ,  "x" ,  {"k": 1} )  ')
        assert op == Append(position=(1, 1), anchor="b1", text="x", attrs={"k": 1})

    def test_empty_text_parses_to_no_ops(self) -> None:
        assert parse("") == ()
        assert parse("# only comments\n") == ()

    def test_parse_error_line_numbers(self) -> None:
        patch = "# c\n\nremove(b1)\nremov(b2)\n"
        with pytest.raises(ParseError) as ei:
            parse(patch)
        assert ei.value.line == 4
        assert "unknown operation" in ei.value.reason

    @pytest.mark.parametrize(
        "line, fragment",
        [
            ("unknown_fn(b1)", "unknown operation"),
            ("remove b1", "expected `name(args)`"),
            ("remove(b1", "expected `name(args)`"),
            ('set_content(b1, "x") extra', "expected `name(args)`"),
            ('set_content(b1, "x"', "expected `name(args)`"),
            ('set_content(b1, "x)', "invalid JSON"),
            ('set_content(b1, 5)', "must be a JSON string"),
            ('set_content("b1", "x")', "expected a bare block id"),
            ('set_attrs(b1, "not-obj")', "must be a JSON object"),
            ('append(b1, "x", "not-obj")', "must be a JSON object"),
            ("remove(b1, b2)", "takes 1 argument"),
            ("remove()", "takes 1 argument"),
            ("move(b1)", "takes 2 argument"),
            ("move(b1, 3)", "expected a bare block id"),
            ('remove(b1,) ', "trailing comma"),
            ('set_content(b1 "x")', "expected ','"),
        ],
    )
    def test_parse_errors(self, line: str, fragment: str) -> None:
        with pytest.raises(ParseError) as ei:
            parse(line)
        assert ei.value.line == 1
        assert fragment in ei.value.reason

    def test_parse_error_to_dict(self) -> None:
        with pytest.raises(ParseError) as ei:
            parse("\n\nnope(")
        d = ei.value.to_dict()
        assert d["error"] == "parse" and d["line"] == 3
        json.dumps(d)  # 可 JSON 序列化


class TestDegrade:
    def test_direct_ops_map_via_ref_map(self) -> None:
        snapshot = _snapshot()
        ref_map = _ref_map(snapshot)
        ops = parse(
            'set_content(b2, "X")\nset_attrs(b3, {"k": 1})\nappend(b1, "Y")\nremove(b4)'
        )
        entries = degrade(ops, ref_map, snapshot)
        core = [op for op, _ in entries]
        assert core == [
            ir.SetContent(key="b2", content="X"),
            ir.SetAttrs(key="b3", attrs={"k": 1}),
            ir.Append(draft_content="Y", draft_attrs={}, at="b1"),
            ir.Remove(key="b4"),
        ]
        # origin 溯源：每条 core op 指回其 surface op 的序号与行号
        assert [o.surface_index for _, o in entries] == [0, 1, 2, 3]
        assert [o.position for _, o in entries] == [(1, 1), (2, 2), (3, 3), (4, 4)]

    def test_head_anchor_maps_to_ir_head(self) -> None:
        snapshot = _snapshot()
        (op, _), *rest = degrade(parse('append(HEAD, "top")'), _ref_map(snapshot), snapshot)
        assert op == ir.Append(draft_content="top", draft_attrs={}, at=ir.HEAD)
        assert rest == []

    def test_move_expands_to_remove_plus_append_with_draft(self) -> None:
        snapshot = _snapshot()
        entries = degrade(parse("move(b1, b3)"), _ref_map(snapshot), snapshot)
        assert [op for op, _ in entries] == [
            ir.Remove(key="b1"),
            # draft 取自 patch 前快照中 b1 的 content / attrs
            ir.Append(draft_content="aaaa", draft_attrs={"start": 0}, at="b3"),
        ]
        assert all(o.surface_index == 0 and o.position == (1, 1) for _, o in entries)

    def test_merge_expands_to_set_content_plus_remove(self) -> None:
        snapshot = _snapshot()
        entries = degrade(parse("merge(b1, b2)"), _ref_map(snapshot), snapshot)
        assert [op for op, _ in entries] == [
            ir.SetContent(key="b1", content="aaaabbbb"),
            ir.Remove(key="b2"),
        ]
        assert all(o.surface_index == 0 for _, o in entries)

    def test_unknown_id_raises_surface_error(self) -> None:
        snapshot = _snapshot()
        with pytest.raises(SurfaceError) as ei:
            degrade(parse("remove(b1)\nremove(b9)"), _ref_map(snapshot), snapshot)
        exc = ei.value
        assert exc.stage == "degrade"
        assert exc.surface_index == 1
        assert exc.position == (2, 2)
        assert exc.expanded == ()
        assert exc.cause is None
        assert "b9" in exc.message
        json.dumps(exc.to_dict())

    def test_head_as_target_rejected(self) -> None:
        snapshot = _snapshot()
        with pytest.raises(SurfaceError) as ei:
            degrade(parse("remove(HEAD)"), _ref_map(snapshot), snapshot)
        assert ei.value.stage == "degrade"
        assert "reserved anchor" in ei.value.message

    def test_replace_expands_to_set_content(self) -> None:
        snapshot = _snapshot()  # b1..b4 = aaaa bbbb cccc dddd
        entries = degrade(parse('replace(b2, "bb", "BB")'), _ref_map(snapshot), snapshot)
        assert [op for op, _ in entries] == [
            # 多处出现全部替换；content 取自 patch 前快照
            ir.SetContent(key="b2", content="BBBB"),
        ]
        assert all(o.surface_index == 0 and o.position == (1, 1) for _, o in entries)

    def test_replace_pattern_not_found(self) -> None:
        snapshot = _snapshot()
        with pytest.raises(SurfaceError) as ei:
            degrade(parse('remove(b1)\nreplace(b2, "zz", "Z")'), _ref_map(snapshot), snapshot)
        exc = ei.value
        assert exc.stage == "degrade"
        assert exc.surface_index == 1
        assert exc.position == (2, 2)
        assert exc.expanded == ()
        assert exc.cause == PATTERN_NOT_FOUND
        assert "zz" in exc.message
        json.dumps(exc.to_dict())


class TestRunPatch:
    def test_set_content_success(self, tmp_path) -> None:
        store, old = _store(tmp_path)
        result = run_patch(store, 'set_content(b2, "NEW")', blockkey_as_is, xml_ish)
        assert result.snapshot_id != old.id
        assert ir.current(store) == result.snapshot_id
        assert len(result.affected) == 1
        ab = result.affected[0]
        assert (ab.key, ab.agent_id, ab.status) == ("b2", "b2", "updated")
        assert ab.annotated == xml_ish("b2", "NEW")
        json.dumps(result.to_dict())
        # 新快照内容
        new = ir.load(store, result.snapshot_id)
        assert "".join(b.content for b in new.blocks) == "aaaaNEWccccdddd"

    def test_append_new_key_from_key_cursor(self, tmp_path) -> None:
        store, _ = _store(tmp_path)  # key_cursor=5
        result = run_patch(store, 'append(b2, "N", {"k": 1})', blockkey_as_is, xml_ish)
        (ab,) = result.affected
        assert (ab.key, ab.agent_id, ab.status) == ("b5", "b5", "appended")
        assert ab.annotated == xml_ish("b5", "N")
        new = ir.load(store, result.snapshot_id)
        assert [b.key for b in new.blocks] == ["b1", "b2", "b5", "b3", "b4"]
        assert new.blocks[2].attrs == {"k": 1}

    def test_append_head_anchor(self, tmp_path) -> None:
        store, _ = _store(tmp_path)
        result = run_patch(store, 'append(HEAD, "top")', blockkey_as_is, xml_ish)
        new = ir.load(store, result.snapshot_id)
        assert [b.key for b in new.blocks][0] == "b5"
        assert new.blocks[0].content == "top"

    def test_move_reports_new_key(self, tmp_path) -> None:
        store, _ = _store(tmp_path)
        result = run_patch(store, "move(b1, b3)", blockkey_as_is, xml_ish)
        (ab,) = result.affected
        assert (ab.key, ab.status) == ("b5", "moved")
        assert ab.annotated == xml_ish("b5", "aaaa")
        new = ir.load(store, result.snapshot_id)
        assert [b.key for b in new.blocks] == ["b2", "b3", "b5", "b4"]

    def test_merge_reports_merged_and_removed(self, tmp_path) -> None:
        store, _ = _store(tmp_path)
        result = run_patch(store, "merge(b1, b2)", blockkey_as_is, xml_ish)
        assert [(ab.key, ab.status) for ab in result.affected] == [
            ("b1", "merged"),
            ("b2", "removed"),
        ]
        merged, removed = result.affected
        assert merged.annotated == xml_ish("b1", "aaaabbbb")
        assert removed.annotated is None
        assert removed.agent_id == "b2"  # 旧 View 下的 id
        new = ir.load(store, result.snapshot_id)
        assert [b.key for b in new.blocks] == ["b1", "b3", "b4"]
        assert new.blocks[0].content == "aaaabbbb"

    def test_replace_success(self, tmp_path) -> None:
        store, old = _store(tmp_path)
        result = run_patch(store, 'replace(b2, "bb", "BB")', blockkey_as_is, xml_ish)
        assert result.snapshot_id != old.id
        (ab,) = result.affected
        assert (ab.key, ab.agent_id, ab.status) == ("b2", "b2", "updated")
        assert ab.annotated == xml_ish("b2", "BBBB")
        json.dumps(result.to_dict())
        new = ir.load(store, result.snapshot_id)
        assert "".join(b.content for b in new.blocks) == "aaaaBBBBccccdddd"

    def test_replace_pattern_not_found_leaves_store_unchanged(self, tmp_path) -> None:
        store, _ = _store(tmp_path)
        before = _store_fingerprint(store)
        with pytest.raises(SurfaceError) as ei:
            run_patch(store, 'replace(b2, "zz", "Z")', blockkey_as_is, xml_ish)
        exc = ei.value
        assert exc.stage == "degrade"
        assert exc.cause == PATTERN_NOT_FOUND
        assert _store_fingerprint(store) == before

    def test_remove_reports_removed(self, tmp_path) -> None:
        store, _ = _store(tmp_path)
        result = run_patch(store, "remove(b4)", blockkey_as_is, xml_ish)
        (ab,) = result.affected
        assert (ab.key, ab.status, ab.annotated) == ("b4", "removed", None)

    def test_affected_ordered_by_document_order(self, tmp_path) -> None:
        store, _ = _store(tmp_path)
        # patch 顺序先 b4 后 HEAD；affected 应按新文档序：b5（文首）在前
        result = run_patch(
            store, 'set_content(b4, "TAIL")\nappend(HEAD, "H")', blockkey_as_is, xml_ish
        )
        assert [(ab.key, ab.status) for ab in result.affected] == [
            ("b5", "appended"),
            ("b4", "updated"),
        ]

    def test_empty_patch_is_noop(self, tmp_path) -> None:
        store, old = _store(tmp_path)
        result = run_patch(store, "# nothing\n", blockkey_as_is, xml_ish)
        assert result.snapshot_id == old.id
        assert result.affected == ()
        assert ir.current(store) == old.id

    def test_apply_failure_traces_back_to_surface_line(self, tmp_path) -> None:
        store, old = _store(tmp_path)
        before = _store_fingerprint(store)
        with pytest.raises(SurfaceError) as ei:
            run_patch(store, "remove(b2)\nset_content(b1, \"X\")\nremove(b2)",
                      blockkey_as_is, xml_ish)
        exc = ei.value
        assert exc.stage == "apply"
        assert exc.surface_index == 2          # 第三条 surface op
        assert exc.position == (3, 3)          # patch 第 3 行
        assert exc.cause == ir.KEY_NOT_FOUND
        assert exc.expanded == (ir.Remove(key="b2"),)
        # store 不变：current 与全部文件内容一致
        assert _store_fingerprint(store) == before
        assert ir.load(store, old.id) == old

    def test_degrade_failure_leaves_store_unchanged(self, tmp_path) -> None:
        store, _ = _store(tmp_path)
        before = _store_fingerprint(store)
        with pytest.raises(SurfaceError) as ei:
            run_patch(store, "remove(b99)", blockkey_as_is, xml_ish)
        assert ei.value.stage == "degrade"
        assert _store_fingerprint(store) == before

    def test_parse_failure_leaves_store_unchanged(self, tmp_path) -> None:
        store, _ = _store(tmp_path)
        before = _store_fingerprint(store)
        with pytest.raises(ParseError):
            run_patch(store, "this is not a call", blockkey_as_is, xml_ish)
        assert _store_fingerprint(store) == before

    def test_multiple_appends_get_sequential_keys(self, tmp_path) -> None:
        store, _ = _store(tmp_path)
        result = run_patch(
            store, 'append(b1, "A")\nmove(b4, b1)', blockkey_as_is, xml_ish
        )
        # 同锚点插入为栈序：move(b4, b1) 落在 b1 正后方，把先插入的 b5 挤后
        # 批次内第 1 个 Append 取 b5，move 的第 2 个取 b6
        assert [(ab.key, ab.status) for ab in result.affected] == [
            ("b6", "moved"),
            ("b5", "appended"),
        ]
        new = ir.load(store, result.snapshot_id)
        assert [b.key for b in new.blocks] == ["b1", "b6", "b5", "b2", "b3"]
