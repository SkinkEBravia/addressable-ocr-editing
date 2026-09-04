# en5-chunk-1t

> 状态：已完成（2026-09-03）

## 问题

chunked doc：同一文档拆成 11 个 chunk，每个 chunk 独立 session、一次机会。修复单位变小后，patch 与 rewrite 的单轮对比是否变化？

## Arms

| arm | 形态 | 说明 |
|---|---|---|
| noop | 锚点 | 不调 LLM，no-correction 基线 |
| rewrite | 单轮重写 | 每 chunk 一次重写机会（11 session） |
| patch-1turn | 块 id 锚补丁 | 每 chunk 一次 patch 机会；best_effort + 隐去 append/merge |

## 命令

### PowerShell（宿主）

```powershell
uv run python -m experiment --dataset datasets/hipe_2026 `
    --toolsets noop,rewrite,patch-1turn --model volc-deepseek-v4-flash `
    --split dev --loaders icdar2017/en/chunk `
    --ids-from "meta:document=periodical__eng_periodical-5" `
    --out runs/en5-chunk-1t --workers 16
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite,patch-1turn --model volc-deepseek-v4-flash \
    --split dev --loaders icdar2017/en/chunk \
    --ids-from "meta:document=periodical__eng_periodical-5" \
    --out runs/en5-chunk-1t --workers 16
```

## 结果

| arm | cmer ↓ [95% CI] | Δ noop [CI] | fixed ↑ | missed ↓ | broken ↓ | halluc ↓ | out tokens | reasoning 占比 |
|---|---|---|---|---|---|---|---|---|
| noop | 0.0928 [0.076, 0.108] | — | 0.0% | 100.0% | 0.0% | 0.0% | 0 | — |
| rewrite | 0.0406 [0.026, 0.056] | -0.0523 [0.041, 0.063] | **74.02%** | **25.98%** | 1.58% | 0.48% | 283k | 97.6% |
| patch-1turn | 0.0413 [0.028, 0.055] | -0.0515 [0.038, 0.062] | 67.63% | 32.37% | **1.10%** | **0.40%** | 316k | 97.6% |

rewrite vs patch-1turn：Δ = -0.0007 [-0.0138, 0.0116]，统计学平手。各 arm 逐 chunk 均值满足 fixed + missed ≡ 100.0%。

## 读法与结论

- chunk 粒度单轮下 patch ≈ rewrite：两者净 cmer 相当，但**细粒度分解显示 patch 的过修率（1.10% vs 1.58%）和幻觉率（0.40% vs 0.48%）依然更优**。由于输入只有单个 chunk，rewrite 的上下文压力较小，其过修劣势未像 doc 粒度那样急剧放大。
- patch 的「只改片段」可见输出优势，被 97%+ 的 reasoning token 完全吃掉，账单上兑现不到。
- 修复前的 0.0790 → 修复后 0.0413：原「rewrite 明显胜出」是 fn 方言不接受带引号 id 造成的假象（8/11 patch 被拒）；方言容错 + best_effort 后两者同效。
- 遗留 1 个 chunk（chunk_16）未修复：模型结尾写 `done` 没带括号，方言整段拒绝。

## 资产与备注

- 报告：`runs/en5-chunk-1t/report.json`；磁带：`runs/en5-chunk-1t/sessions/`
- 同为 replay 重放后的结果（`--replay-with patch-1turn=patch-1turn-lenient`），未重打 API。
- chunk 得分 = 逐块均值口径，与 doc 整篇口径不直接比绝对值。
