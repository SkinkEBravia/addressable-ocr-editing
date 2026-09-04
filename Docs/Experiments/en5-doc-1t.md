# en5-doc-1t

> 状态：已完成（2026-09-03）

## 问题

one shot doc：整篇 doc 首轮注入，每 arm 只给一次机会，谁修得好？单轮口径下 patch 与 rewrite 的横向对比基线。

## Arms

| arm | 形态 | 说明 |
|---|---|---|
| noop | 锚点 | 不调 LLM，no-correction 基线 |
| rewrite | 单轮全文重写 | 一口气重写整篇（JSON 输出条款） |
| patch-1turn | 块 id 锚补丁 | 一次 patch 机会；应用策略 best_effort（失败 op 跳过），隐去 append/merge |

## 命令

### PowerShell（宿主）

```powershell
uv run python -m experiment --dataset datasets/hipe_2026 `
    --toolsets noop,rewrite,patch-1turn --model volc-deepseek-v4-flash `
    --split dev --loaders icdar2017/en/doc `
    --ids "icdar2017/periodical__eng_periodical-5" `
    --out runs/en5-doc-1t --workers 3
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite,patch-1turn --model volc-deepseek-v4-flash \
    --split dev --loaders icdar2017/en/doc \
    --ids "icdar2017/periodical__eng_periodical-5" \
    --out runs/en5-doc-1t --workers 3
```

## 结果

| arm | status | cmer ↓ | Δ vs noop | fixed ↑ | missed ↓ | broken ↓ | halluc ↓ | out tokens | reasoning 占比 |
|---|---|---|---|---|---|---|---|---|---|
| noop | done | 0.0928 | — | 0.0% | 100.0% | 0.0% | 0.0% | 0 | — |
| rewrite | done | 0.0473 | -0.0455 | **78.82%** | **21.18%** | **2.92%** | **0.99%** | 61.2k | 93.4% |
| patch-1turn | budget_exceeded（设计内） | **0.0346** | **-0.0583** | 71.27% | 28.73% | **0.78%** | **0.31%** | 83.2k | 91.9% |

*注：各 arm 严格满足 fixed + missed ≡ 100.0% 原文错误基数。*

## 读法与结论

- **patch 单轮反超 rewrite 0.0128 的本质是「抗过修与抑幻觉」**：
  - 传统 CMER 只能看到 patch 胜出，新指标揭示了深层原因：rewrite 虽修对了更多错（78.82% vs 71.27%），但在全篇重写中造成了高达 **2.92% 的过修改坏率和 0.99% 的幻觉插入**；
  - patch 将**改坏率死死压在 0.78%（仅为 rewrite 的 1/4）、幻觉仅 0.31%（仅为 rewrite 的 1/3）**！大文本修复的关键在于“不把原本正确的内容改坏”。
- 结论：单轮 doc 粒度，**patch(块锚 + best_effort) > rewrite > noop**。
- 教训沉淀：patch-1turn 的 status 恒为 budget_exceeded（没机会说 done()），看指标不看 status。

## 资产与备注

- 报告：`runs/en5-doc-1t/report.json`；磁带：`runs/en5-doc-1t/sessions/`
- patch 臂的结果是 replay 重放产物：`--replay-with patch-1turn=patch-1turn-lenient`（方言修复带引号 id + best_effort 应用），未重打 API；replay 段有记录。
- doc 级 rewrite 产出对不齐 chunk 边界（chunks_aligned=0），按整篇评分；与其他粒度对比只看趋势。
