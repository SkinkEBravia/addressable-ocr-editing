# HIPE-OCRepair-2026 数据集构成（v0.9）

> 本文基于 `related_source/HIPE-OCRepair-2026-data-0.9.5/data/v0.9` 的实读统计（2026-09-02）。
> 装载与评分入口见 `datasets/hipe_2026/dataset.py`；设计契约见 [Design/10-datasets.md](Design/10-datasets.md)。

## 记录单位

**一行 = 一个 chunk = 一页的转写单元**。整篇源文档被拆成页；`document_id` 形如
`1886-eschstruth_katz_l0_p025`（`源文档_退化级_页码`）。

每行字段：

| 字段 | 内容 |
|---|---|
| `document_metadata` | `document_id`、`primary_dataset_name/filename/version/license/doi` 等 |
| `ground_truth.transcription_unit` | gold 文本（页内以 `\n` 分行） |
| `ocr_hypothesis.transcription_unit` | OCR 原文（修复对象） |
| `ocr_postcorrection_output` | 提交位：竞赛系统输出 + 质量报告（原始数据中为占位 `-1` / `"None"`） |

## 子集 × 语言 × split（行数，字符均值为 ocr_hypothesis 长度）

| 子集 | 语言 | 特点 | dev | train | test | masked-test |
|---|---|---|---|---|---|---|
| dta19-l0 | de | 书籍页；11 篇源文档 × 抽样 10 页 | 110 | 190 | — | 80 |
| dta19-l1 | de | 同上，退化加重 | 110 | 190 | — | 80 |
| dta19-l2 | de | 同上，退化最重 | 110 | 190 | — | 80 |
| icdar2017 | en | 页均 ~1800 字符 | 188 | 455 | 101 | 100 |
| icdar2017 | fr | 页均 ~2700 字符 | — | 391 | 100 | 100 |
| impresso-nzz | de | 报纸长文，~10300 字符/条 | — | 150 | 17 | — |
| impresso-snippets | de/en/fr | 短片段 ~500–600 字符 | 10×3 | 50×3 | 100×3 | 100×3 |
| overproof | en | ~2000 字符 | 30 | 146 | 32 | — |

- dta19 三个退化级共享同一批 11 篇源文档与同样的页码抽样（页字符数
  min/avg/max ≈ 65 / 1450 / 7900，随退化级略增）。
- dta19 另有 `*-unmatched` 文件（dev 100 / train 180 每级），疑似 OCR 与 gold
  对齐失败的行，官方计分不纳入（此语义未向官方文档核实）。
- masked-test 无 reference（`reference=None`），不出数。
- 页内规模跨度大（65–7908 字符），长页主要是散文页，短页多为诗歌/标题页。

## 源文档 ↔ 页对照（dta19 dev，每级 11 篇 × 10 页）

| 源文档 | dev 抽样页 |
|---|---|
| 1797-wackenroder_herzensergiessungen | p036, p047, p049, p050, p064, p072, p109, p115, p119, p138 |
| 1804-paul_flegeljahre01 | p016, p026, p028, p087, p104, p166, p168, p187, p205, p221 |
| 1828-platen_gedichte | p001, p016, p043, p055, p098, p100, p103, p105, p124, p125 |
| 1834-wienbarg_feldzuege | p017, p031, p035, p037, p118, p122, p143, p170, p249, p264 |
| 1852-storm_gedichte | p001, p003, p009, p010, p029, p030, p044, p071, p076, p091 |
| 1871-bauer_buehnenleben | p030, p036, p041, p044, p065, p066, p124, p244, p249, p273 |
| 1879-vischer_auch02 | p062, p116, p127, p192, p205, p225, p232, p265, p333, p344 |
| 1886-eschstruth_katz | p014, p025, p091, p106, p109, p111, p120, p169, p173, p187 |
| 1897-poersch_gewerkschaftsbewegung | p004–p006, p009, p012–p015, p017, p018 |
| 1898-andreas_fenitschka | p004, p013, p020, p024, p026, p061, p064, p114, p139, p141 |
| 1898-bismarck_erinnerungen02 | p049, p068, p098, p110, p125, p209, p243, p277, p293, p296 |

抽样页不连续——dev 的"文档"是 10 页摘录，不是全书。

## 对本项目口径的影响

- **chunk 粒度（逐页）与官方可比**；doc 粒度（同源文档 10 页拼接，~14k 字符）
  是自设口径，得分 = chunk 均值 + 方差。
- 分组键必须是**源文档**（`document_id` 剥掉 `_lX_pYYY` 后缀或
  `primary_dataset_filename` 末段），页按页码排序以 `\n` 拼接，
  gold_units = 逐页 gold。注意：v1 实现曾误用 `document_id` 全名作分组键，
  因其中含页码导致 doc ≡ chunk（doc 任务恒为单 chunk、cmer_var 恒 0）。
