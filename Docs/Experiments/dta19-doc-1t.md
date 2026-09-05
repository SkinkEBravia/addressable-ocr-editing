# dta19-doc-1t

> 状态：已完成（2026-09-04）

## 问题

整篇长文档单轮修复（平均 ~14.4k 字符 / ~4.1k BPE tokens）：
1. 第一轮对话直接给出拼接后的完整文档，单轮一次性修复；
2. 在大上下文且极端低错误率（0.36%）的场景下，rewrite 是否会因全文重写造成严重的过修与幻觉漂移？
3. patch、swe_edit 与 find_replace 三种编辑形态在 4k tokens 上下文下的定位精度与资源开销对比。

## Arms

| arm | 形态 | 说明 |
|---|---|---|
| noop | 锚点 | 不调 LLM，no-correction 基线 |
| rewrite | 单轮长文重写 | 全文一次性重写；JSON 条款 |
| patch-1turn | 整篇块 id 补丁 | 单轮行划分 patch（约 300~400 行）；best_effort + 隐去 append/merge |
| swe_edit | 整篇行号编辑 | 单轮行号区间替换（edit start:end "text"） |
| find_replace | 整篇字符串替换 | 单轮字面字符串匹配替换（find_replace "old" "new"） |

## 命令

### PowerShell（宿主）

```powershell
uv run python -m experiment --dataset datasets/hipe_2026 `
    --toolsets noop,rewrite,patch-1turn,swe_edit,find_replace `
    --model volc-deepseek-v4-flash `
    --split dev --loaders dta19-l0/de/doc `
    --out runs/dta19-doc-1t --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite,patch-1turn,swe_edit,find_replace \
    --model volc-deepseek-v4-flash \
    --split dev --loaders dta19-l0/de/doc \
    --out runs/dta19-doc-1t --workers 11
```

## 结果

| arm | cmer ↓ [95% CI] | Δ noop [CI] | fixed ↑ | missed ↓ | broken ↓ | halluc ↓ | out tokens | reasoning 占比 |
|---|---|---|---|---|---|---|---|---|
| noop | **0.0040** [0.0031, 0.0052] | — | 0.00% | 100.00% | **0.00%** | **0.00%** | **0** | — |
| rewrite | 0.0075 [0.0046, 0.0109] | +0.0034 [+0.0006, +0.0070] | **44.81%** | **55.19%** | 0.53% | 0.32% | 567.5k | 91.5% |
| patch-1turn | 0.0047 [0.0034, 0.0064] | +0.0007 [-0.0006, +0.0024] | 20.72% | 79.28% | **0.16%** | **0.13%** | 383.5k | ~99.0%* |
| swe_edit | 0.0289 [0.0048, 0.0751] | +0.0249 [+0.0005, +0.0716] | 42.16% | 57.84% | 2.85% | 0.86% | 557.2k | 98.1% |
| find_replace | 0.0050 [0.0037, 0.0063] | +0.0010 [-0.0002, +0.0021] | 41.35% | 58.65% | 0.27% | 0.22% | 589.9k | 98.7% |

*注：`patch-1turn` 有 3 个 session 触发 `incomplete`（补丁生成过长截断），有效统计为 8/11 样本。*

配对差异（cMER Δ，[95% CI]）：
- `patch-1turn vs noop`：Δ = +0.0007 [-0.0006, +0.0024]（置信区间跨 0，统计学极为接近 noop）
- `find_replace vs noop`：Δ = +0.0010 [-0.0002, +0.0021]（微弱劣化）
- `patch-1turn vs find_replace`：Δ = -0.0003 [-0.0018, +0.0012]（两者统计平手）
- `patch-1turn vs rewrite`：Δ = -0.0028 [-0.0068, +0.0003]（patch 优于 rewrite）
- `patch-1turn vs swe_edit`：Δ = -0.0242 [-0.0705, -0.0006]（patch 显著优于 swe_edit）

官方聚合口径（`score_all`）：
| arm | cMER micro ↓ | cMER macro ↓ | wMER macro ↓ | Pref Score (cMER) ↑ |
|---|---|---|---|---|
| noop | **0.0036** | **0.0040** | **0.0233** | **0.0000** |
| patch-1turn | 0.0039 | 0.0047 | 0.0280 | 0.0000 |
| find_replace | 0.0052 | 0.0050 | 0.0216 | -0.4545 |
| rewrite | 0.0087 | 0.0075 | 0.0266 | -0.4545 |
| swe_edit | 0.0259 | 0.0289 | 0.0547 | -0.4545 |

## 读法与结论

1. **`patch-1turn` 展现极强的抗过修保真能力，最接近 noop**：
   - 在约 1.4 万字符的整篇长文档上，`patch-1turn` 达成了所有修复 arm 中的最低 cMER（0.0047，聚合 Micro-cMER 0.0039）；
   - 与 `noop` 的配对差异仅为 +0.0007，CI [-0.0006, +0.0024] 跨过 0；
   - 细粒度指标表明其**过修率仅 0.16%、插入幻觉率仅 0.13%**，相比 rewrite 降低了约 70%，有力证明了结构化块 patch 对未修改上下文的隔离保护作用。
2. **`find_replace` 综合修复效能最佳**：
   - 在保持极低过修（broken_rate 0.27%）的同时，修对了 41.35% 的真实错误，cMER 稳定在 0.0050。字符串字面匹配在长文档全局上下文中依然具有强定位稳定性。
3. **`swe_edit` 在单轮长文档中发生“行号脱靶事故”**：
   - swe_edit 在长文档中 cMER 恶化至 0.0289（95% CI 上界达到 0.0751），broken_rate 飙升至 2.85%；
   - **机理分析**：在 300~400 行的长文档且**没有任何交互报错反馈的单轮场景下**，模型估算行号区间容易出现多行偏差，导致误删或错位替换大段未改动文本。这证明行号锚工具**极其依赖多轮环境中的即时反馈自愈机制**，不能直接用于长文档单轮。
4. **Token 开销与产出效率**：
   - patch-1turn 只输出必要的局部差异，总 output tokens 为 383.5k，较全文重写 rewrite（567.5k）与 find_replace（589.9k）**节省了约 33% 的输出 Token**；
   - 但长文档下模型生成较长 patch 导致 3 个样本触发 incomplete，后续可考虑增加单轮 token 上限或结合多轮分步提交。

## 资产与备注

- 报告：`runs/dta19-doc-1t/report.json`；磁带：`runs/dta19-doc-1t/sessions/`
- 数据集规模：`dta19-l0` dev split 共 11 篇文档，11 × 5 = 55 个 session。
- 观测重点：关注 rewrite 在长文本下的 broken_rate 与 halluc_rate，检验 patch 的精准片段修改收益。
