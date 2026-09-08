"""hipe_2026 结构测试：chunk 原子装载、doc 分组口径、loader 注册表。

对应 Docs/HIPE_info.md 的实读统计口径（v0.9，2026-09-02）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from datasetkit import Task, load_dataset, resolve

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dataset():
    return load_dataset(ROOT / "datasets" / "hipe_2026")


def test_loader_keys_cover_subset_lang_granularity(dataset):
    keys = set(dataset.loaders(split="dev"))
    assert "icdar2017/en/chunk" in keys
    assert "icdar2017/en/doc" in keys
    assert "dta19-l0/de/chunk" in keys
    assert "dta19-l2/de/doc" in keys
    assert "impresso-snippets/fr/chunk" in keys


def test_chunk_counts_match_census(dataset):
    """行数与 Docs/HIPE_info.md 普查一致。"""
    assert len(resolve(dataset, split="dev", keys=["dta19-l0/de/chunk"])) == 110
    assert len(resolve(dataset, split="dev", keys=["icdar2017/en/chunk"])) == 188
    assert (
        len(resolve(dataset, split="train", keys=["impresso-snippets/de/chunk"]))
        == 50
    )


def test_subset_all_languages_via_chaining(dataset):
    """icdar2017,all = en + fr 两条 loader 串联（组合权在调用方）。"""
    en = resolve(dataset, split="train", keys=["icdar2017/en/chunk"])
    fr = resolve(dataset, split="train", keys=["icdar2017/fr/chunk"])
    both = resolve(
        dataset, split="train", keys=["icdar2017/en/chunk", "icdar2017/fr/chunk"]
    )
    assert len(both) == len(en) + len(fr) == 455 + 391
    assert {t.meta["language"] for t in both} == {"en", "fr"}


def test_doc_grouping_dta19(dataset):
    """dta19 dev 每级 11 篇源文档 × 10 页（v1 分组键 bug 的回归测试）。"""
    docs = resolve(dataset, split="dev", keys=["dta19-l0/de/doc"])
    assert len(docs) == 11
    assert all(t.meta["n_chunks"] == 10 for t in docs)
    doc = docs[0]
    assert doc.meta["unit_boundaries"] == sorted(doc.meta["unit_boundaries"])


def test_doc_grouping_icdar2017(dataset):
    """icdar2017 dev en：8 篇源文档；最长 = eng_periodical-3（51 chunks）。"""
    docs = resolve(dataset, split="dev", keys=["icdar2017/en/doc"])
    assert len(docs) == 8
    longest = max(docs, key=lambda t: len(t.input))
    assert longest.task_id == "icdar2017/periodical__eng_periodical-3"
    assert longest.meta["n_chunks"] == 51
    # chunk 流与 doc 流自洽：同一文档的 chunk 拼接 == doc 输入
    chunks = [
        t
        for t in resolve(dataset, split="dev", keys=["icdar2017/en/chunk"])
        if t.meta["document"] == "periodical__eng_periodical-3"
    ]
    assert len(chunks) == 51
    assert sum(len(t.input) for t in chunks) + 50 * len("\n") == len(longest.input)


def test_doc_equiv_chunk_subsets(dataset):
    """impresso-nzz / overproof：每条即独立文档，doc ≡ chunk。"""
    for key in ("impresso-nzz/de/test", "overproof-combined/en/dev"):
        subset, lang, split = key.split("/")
        chunks = resolve(dataset, split=split, keys=[f"{subset}/{lang}/chunk"])
        docs = resolve(dataset, split=split, keys=[f"{subset}/{lang}/doc"])
        assert len(docs) == len(chunks)
        assert all(t.meta["n_chunks"] == 1 for t in docs)


def test_masked_test_reference_none(dataset):
    tasks = resolve(dataset, split="masked-test", keys=["icdar2017/en/chunk"], limit=10)
    assert tasks
    assert all(t.reference is None for t in tasks)


def test_meta_filter_selects_article_chunks(dataset):
    """--ids-from meta:document=... 等价于按 document 过滤出目标文章的 51 chunks。"""
    chunks = resolve(
        dataset,
        split="dev",
        keys=["icdar2017/en/chunk"],
        meta={"document": "periodical__eng_periodical-3"},
    )
    assert len(chunks) == 51
    assert all(
        t.task_id.startswith("icdar2017/periodical__eng_periodical-3#") for t in chunks
    )


def test_doc_scorer_aligned(dataset):
    """doc 粒度评分：identity 预测时 cmer = cmer_hyp 且 chunks_aligned=1。"""
    docs = resolve(dataset, split="dev", keys=["icdar2017/en/doc"])
    doc = next(t for t in docs if t.task_id == "icdar2017/periodical__eng_periodical-3")
    record = dataset.scorer().score(doc.input, doc)
    assert record["chunks_aligned"] == 1.0
    assert record["n_chunks"] == 51.0
    assert record["cmer"] == pytest.approx(record["cmer_hyp"])


def test_key_leak_metric(dataset):
    """key 泄漏：产出行首出现 num-key 形态前缀即计数（单列，不进 broken）。"""
    task = Task(
        task_id="t/synth",
        input="hello wrld\n",
        reference="hello world\n",
        meta={},
    )
    clean = dataset.scorer().score("hello world\n", task)
    assert clean["key_leak"] == 0.0
    leaked = dataset.scorer().score("1: hello world\n12: extra\n", task)
    assert leaked["key_leak"] == 2.0
