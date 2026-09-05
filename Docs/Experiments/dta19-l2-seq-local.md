# dta19-l2-seq-local

> 状态：已完成（2026-09-05）

## 问题

在高错误率重度退化德语子集（`dta19-l2`，官方基线 CMER 约 5.46%）上，流式连续 chunk 输入（Scope-Constrained 单机会，禁止跨 chunk 回溯）：
1. **重噪流式局部约束承载力**：当每页 OCR 错误密集（破损、乱码、粘连严重）时，局部每轮独立编号能否降低模型在多轮长会话中的认知负荷？
2. **长对话历史抗衰减性**：测试随着 10 轮对话递进、历史 token 积累，模型在后续轮次（第 7~10 轮）的修错能力是否发生退化，是否会出现前文重度噪音污染当前上下文的现象；
3. **工具方案在重噪下的最终分水岭**：检验 `patch_seq`、`find_replace_seq`、`swe_edit_seq` 与 `rewrite_seq` 在重度退化多轮场景下的召回、过修与失败率。

## Arms

| arm | 形态 | 说明 |
|---|---|---|
| noop | 锚点 | 不调 LLM，no-correction 基线 |
| rewrite_seq | 顺序重写 | 每轮呈现一个 chunk 原文，模型提交重写文本；无反馈 |
| patch_seq | 局部块 id 补丁 | 每轮呈现一个 chunk 的块标注（每轮独立 b1 起排）；无反馈；best_effort |
| swe_edit_seq | 局部行号编辑 | 每轮呈现当前 chunk 行号（1 起编），仅可编辑当前 chunk（edit 1:N << end） |
| find_replace_seq | 局部字符串替换 | 每轮呈现当前 chunk，替换仅在当前 chunk 生效 |

## 命令

### PowerShell（宿主）

```powershell
uv run python -m experiment --dataset datasets/hipe_2026 `
    --toolsets noop,rewrite_seq,patch_seq,swe_edit_seq,find_replace_seq `
    --model volc-deepseek-v4-flash `
    --split dev --loaders dta19-l2/de/doc `
    --out runs/dta19-l2-seq-local --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite_seq,patch_seq,swe_edit_seq,find_replace_seq \
    --model volc-deepseek-v4-flash \
    --split dev --loaders dta19-l2/de/doc \
    --out runs/dta19-l2-seq-local --workers 11
```

## 结果

| arm | cmer ↓ [95% CI] | Δ vs noop [CI] | fixed ↑ | missed ↓ | broken ↓ | halluc ↓ | out tokens | reasoning 占比 |
|---|---|---|---|---|---|---|---|---|
| noop | 0.0580 [0.0549, 0.0607] | — | 0.00% | 100.00% | **0.00%** | **0.00%** | **0** | — |
| rewrite_seq | 0.0304 [0.0219, 0.0412] | -0.0276 [-0.0370, -0.0165] | 62.30% | 37.70% | 0.91% | 0.42% | **1.1M** | — |
| patch_seq | 0.0269 [0.0187, 0.0363] | -0.0310 [-0.0401, -0.0216] | 65.96% | 34.04% | **0.74%** | **0.33%** | 1.3M | — |
| swe_edit_seq | 0.0328 [0.0216, 0.0466] | -0.0252 [-0.0369, -0.0123] | 74.17% | 25.83% | 1.93% | 0.71% | 1.3M | — |
| find_replace_seq | **0.0198** [0.0168, 0.0229] | **-0.0381** [-0.0426, -0.0340] | **81.72%** | **18.28%** | 0.97% | 0.44% | 1.4M | 94.8% |

*注：在重度退化（L2）下多轮历史累积较长，触发 incomplete 截断数分别为：`rewrite_seq` (3/11), `patch_seq` (2/11), `swe_edit_seq` (1/11)，而 `find_replace_seq` 为 **0 失败（11/11 全胜）**。*

配对差异（cMER Δ，[95% CI]）：
- `find_replace_seq vs noop`：Δ = -0.0381 [-0.0426, -0.0340]（**find_replace 狂砍 65% 相对错误率**）
- `find_replace_seq vs patch_seq`：Δ = -0.0071 [-0.0145, -0.0003]（find_replace 显著优于 patch_seq）
- `find_replace_seq vs rewrite_seq`：Δ = -0.0105 [-0.0211, -0.0026]（find_replace 显著优于 rewrite_seq）
- `find_replace_seq vs swe_edit_seq`：Δ = -0.0130 [-0.0272, -0.0025]（find_replace 显著优于 swe_edit_seq）
- `patch_seq vs rewrite_seq`：Δ = -0.0034 [-0.0188, +0.0100]（两者统计平手）

官方聚合口径（`score_all`）：
| arm | cMER micro ↓ | cMER macro ↓ | wMER macro ↓ | Pref Score (cMER) ↑ |
|---|---|---|---|---|
| noop | 0.0585 | 0.0580 | 0.2962 | +0.0000 |
| find_replace_seq | **0.0215** | **0.0198** | **0.0897** | **+1.0000** |
| patch_seq | 0.0327 | 0.0269 | 0.1339 | +0.8182 |
| rewrite_seq | 0.0301 | 0.0304 | 0.1368 | +0.7273 |
| swe_edit_seq | 0.0337 | 0.0328 | 0.1206 | +0.7273 |

## 读法与结论

1. **`find_replace_seq` 展现统治级性能：唯一攻入 1.98% 错误率大关**：
   - 在基准错误率高达 ~5.8% 的极重度退化环境（L2）下，`find_replace_seq` 将 cMER 压低至 **0.0198**（官方聚合 Micro cMER 0.0215）；
   - 修错召回率高达 **81.72%**，Preference 达到满分 **+1.0000**（全量文档 100% 跑赢 noop）；
   - **零失败稳定性**：在其他方案均出现 1~3 例截断的情况下，`find_replace_seq` 达成 11/11 满分通过，证明字面字符串匹配在重度噪点下的鲁棒性最强。
2. **重噪下的形态分化**：
   - `patch_seq`（0.0269）保持极低过修（0.74%），在长多轮中表现仅次于 find_replace；
   - `swe_edit_seq`（0.0328）虽然也大幅跑赢 noop，但随着噪点变密，单轮内定位行号的误差率提升（broken 达 1.93%）；
   - `rewrite_seq`（0.0304）因重度噪点导致多轮自回归生成冗长，遭遇了 3 例 incomplete 截断。
3. **L0 -> L1 -> L2 纵向终极结论**：
   - 随着噪声从轻到重（0.4% -> 2.4% -> 5.8%），模型纠错从“过修惩罚（越修越差）”完全转变为“超额收益（大幅压降错误）”；
   - 在所有交互与工具形态中，**`find_replace` 结合局部流式输入（seq-local）展现出了跨越全退化级的最强韧性与综合最优效能**。

## 资产与备注

- 报告：`runs/dta19-l2-seq-local/report.json`；磁带：`runs/dta19-l2-seq-local/sessions/`
- 数据集规模：`dta19-l2` dev split 共 11 篇文档，每篇文档 10 个 chunk（总计 11 × 5 = 55 个 session）。
- 观测重点：重点观察在 >5% 严重噪音下，局部补丁 `patch_seq` 与局部字符串替换 `find_replace_seq` 的净修错率及长多轮稳定性。
