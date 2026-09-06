from pathlib import Path
import pytest
from datasetkit import Task, load_dataset

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def hipe():
    return load_dataset(ROOT / "datasets" / "hipe_2026")


def test_decomposition_perfect_repair(hipe):
    """完美修复：H == G => fixed_rate = 1.0, broken_rate = 0, halluc_ins = 0, missed_rate = 0."""
    res = hipe._decompose_alignment(reference="hello world", ocr="helo wrld", hypothesis="hello world")
    assert res["fixed_rate"] == 1.0
    assert res["broken_rate"] == 0.0
    assert res["halluc_ins"] == 0.0
    assert res["missed_rate"] == 0.0


def test_decomposition_noop(hipe):
    """noop：H == I => fixed_rate = 0, broken_rate = 0, missed_rate = 1.0, halluc_ins = 0."""
    # 纯替换与缺失
    res1 = hipe._decompose_alignment(reference="hello world", ocr="helo wrld", hypothesis="helo wrld")
    assert res1["fixed_rate"] == 0.0
    assert res1["broken_rate"] == 0.0
    assert res1["missed_rate"] == 1.0
    assert res1["halluc_ins"] == 0.0

    # 原文包含插入错误（多余字符）的 noop
    res2 = hipe._decompose_alignment(reference="hello world", ocr="helo wrld extra", hypothesis="helo wrld extra")
    assert res2["fixed_rate"] == 0.0
    assert res2["broken_rate"] == 0.0
    assert res2["missed_rate"] == 1.0
    assert res2["halluc_ins"] == 0.0

    # 原文包含多余字符，模型将其成功剔除
    res3 = hipe._decompose_alignment(reference="hello world", ocr="helo wrld extra", hypothesis="hello world")
    assert res3["fixed_rate"] == 1.0
    assert res3["broken_rate"] == 0.0
    assert res3["missed_rate"] == 0.0
    assert res3["halluc_ins"] == 0.0


def test_decomposition_pure_hallucination(hipe):
    """纯幻觉插入：在原本正确文本后插入无关内容 => halluc_ins > 0, fixed_rate = 0."""
    res = hipe._decompose_alignment(reference="hello", ocr="hello", hypothesis="hello world")
    assert res["halluc_ins"] > 0.0
    assert res["fixed_rate"] == 0.0


def test_decomposition_over_correction(hipe):
    """纯过修：将正确字符改错 => broken_rate > 0, fixed_rate = 0."""
    res = hipe._decompose_alignment(reference="hello", ocr="hello", hypothesis="hallo")
    assert res["broken_rate"] > 0.0
    assert res["fixed_rate"] == 0.0
    assert res["missed_rate"] == 0.0


def test_decomposition_zero_division_safety(hipe):
    """除零安全测试：原文全对、原文全错、空串等边界情况不抛 ZeroDivisionError."""
    # 原文全对
    res_correct = hipe._decompose_alignment(reference="abc", ocr="abc", hypothesis="abc")
    assert res_correct["fixed_rate"] == 0.0
    assert res_correct["missed_rate"] == 0.0
    assert res_correct["broken_rate"] == 0.0
    assert res_correct["halluc_ins"] == 0.0

    # 原文全错
    res_wrong = hipe._decompose_alignment(reference="abc", ocr="xyz", hypothesis="xyz")
    assert isinstance(res_wrong["fixed_rate"], float)
    assert isinstance(res_wrong["broken_rate"], float)

    # 空串
    res_empty = hipe._decompose_alignment(reference="", ocr="", hypothesis="")
    assert res_empty["fixed_rate"] == 0.0
    assert res_empty["broken_rate"] == 0.0


def test_scorer_integration_chunk(hipe):
    """集成测试：scorer 对单 chunk Task 产出完整的指标字典且 cmer 保真."""
    s = hipe.scorer()
    task = Task(
        task_id="t1",
        input="helo wrld",
        reference="hello world",
        meta={},
    )
    res = s.score("hello world", task)
    assert res["cmer"] == 0.0
    assert res["cmer_hyp"] > 0.0
    assert res["fixed_rate"] == 1.0
    assert res["broken_rate"] == 0.0
    assert res["missed_rate"] == 0.0
    assert res["halluc_ins"] == 0.0


def test_scorer_integration_doc(hipe):
    """集成测试：scorer 对 doc 粒度（多单元拼接）逐 chunk 均值聚合."""
    s = hipe.scorer()
    task = Task(
        task_id="d1",
        input="helo\nwrld",
        reference="hello\nworld",
        meta={"gold_units": ["hello", "world"]},
    )
    # 单元 1 完美修复，单元 2 未修
    res = s.score("hello\nwrld", task)
    assert "cmer" in res
    assert "cmer_var" in res
    assert "fixed_rate" in res
    assert "broken_rate" in res
    assert "missed_rate" in res
    assert "halluc_ins" in res
    assert 0.0 < res["fixed_rate"] < 1.0  # 两个单元的均值


# --- 批 0.5 新增：S/D/I 子分量与选择率 ---


def test_decomposition_subcomponents_sum_to_rates(hipe):
    """九个子分量必须与四个聚合率自洽（同一分母）。"""
    res = hipe._decompose_alignment(
        reference="hello world", ocr="helo wrld extra", hypothesis="hallo world"
    )
    n_err = res["n_errors_ocr"]
    n_cor = res["n_correct_ocr"]
    assert n_err > 0 and n_cor > 0

    fixed = res["fixed_sub"] + res["fixed_del"] + res["fixed_ins_del"]
    missed = res["missed_sub"] + res["missed_del"] + res["missed_ins"]
    broken = res["broken_sub"] + res["broken_del"] + res["broken_ins"]

    assert fixed / n_err == pytest.approx(res["fixed_rate"])
    assert missed / n_err == pytest.approx(res["missed_rate"])
    assert broken / n_cor == pytest.approx(res["broken_rate"])


def test_decomposition_over_correction_is_substitution(hipe):
    """把正确字符改错 => 破坏计入 broken_sub，而非 broken_del/broken_ins。"""
    res = hipe._decompose_alignment(reference="hello", ocr="hello", hypothesis="hallo")
    assert res["broken_sub"] > 0
    assert res["broken_del"] == 0
    assert res["broken_ins"] == 0


def test_decomposition_dropped_text_is_deletion(hipe):
    """漏抄（复制失败）=> 破坏计入 broken_del，而非 broken_sub。"""
    res = hipe._decompose_alignment(
        reference="hello world", ocr="hello world", hypothesis="hello"
    )
    assert res["broken_del"] > 0
    assert res["broken_sub"] == 0


def test_selection_stats_identity(hipe):
    """输出与输入完全相同 => 零改动。"""
    res = hipe._selection_stats("hello world", "hello world")
    assert res["edit_spans"] == 0.0
    assert res["edited_chars"] == 0.0


def test_selection_stats_counts_regions(hipe):
    """选择率数的是「改了多少地方」，不是改了多少字符。"""
    one = hipe._selection_stats("helo world", "hello world")
    assert one["edit_spans"] >= 1
    assert one["edited_chars"] >= 1

    two = hipe._selection_stats("aaa bbb ccc", "xxx bbb yyy")
    assert two["edit_spans"] >= 2
    assert two["edit_spans"] > one["edit_spans"]


def test_selection_stats_is_arm_agnostic(hipe):
    """rewrite 无显式 op，选择率仍可由 input↔output 对齐得出（这是其存在意义）。"""
    rewritten = hipe._selection_stats("teh quick brovvn fox", "the quick brown fox")
    assert rewritten["edit_spans"] >= 2
