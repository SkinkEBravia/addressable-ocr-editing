# dta19-seq-local

> 状态：已完成（2026-09-05）

## 问题

流式连续 chunk 输入（Scope-Constrained，单机会，禁止跨 chunk 修复）：
1. 每个 session 对应一篇完整文档，以多轮对话方式每轮流式输入一个新的 chunk；
2. 每一轮只能对当前呈现的 chunk 进行修复，行号与块 ID 每 chunk 重新从 1 编排；
3. 测试各工具在局部作用域约束下，随对话轮数增加、前文历史累积时的纠错与抗过修表现。

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
    --split dev --loaders dta19-l0/de/doc `
    --out runs/dta19-seq-local --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite_seq,patch_seq,swe_edit_seq,find_replace_seq \
    --model volc-deepseek-v4-flash \
    --split dev --loaders dta19-l0/de/doc \
    --out runs/dta19-seq-local --workers 11
```

## 结果

| arm | cmer ↓ [95% CI] | Δ vs noop [CI] | fixed ↑ | missed ↓ | broken ↓ | halluc ↓ | out tokens | reasoning 占比 |
|---|---|---|---|---|---|---|---|---|
| noop | **0.0040** [0.0031, 0.0052] | — | 0.00% | 100.00% | **0.00%** | **0.00%** | **0** | — |
| rewrite_seq | 0.0062 [0.0048, 0.0078] | +0.0022 [+0.0007, +0.0038] | **44.05%** | **55.95%** | 0.41% | 0.29% | 966.2k | 93.6% |
| patch_seq | 0.0059 [0.0047, 0.0071] | +0.0018 [+0.0005, +0.0032] | 42.98% | 57.02% | 0.36% | 0.27% | **746.7k** | 98.6% |
| swe_edit_seq | 0.0093 [0.0061, 0.0128] | +0.0053 [+0.0025, +0.0086] | 41.82% | 58.18% | 0.70% | 0.40% | 986.7k | 97.9% |
| find_replace_seq | **0.0050** [0.0037, 0.0063] | **+0.0010** [-0.0002, +0.0022] | 41.40% | 58.60% | **0.27%** | **0.20%** | 779.6k | 98.3% |

*注：总计 55 个 session 中 54 个 done，`rewrite_seq` 有 1 个 session 触发 `incomplete`（多轮历史长文本截断）。*

配对差异（cMER Δ，[95% CI]）：
- `find_replace_seq vs noop`：Δ = +0.0010 [-0.0002, +0.0022]（**置信区间覆盖 0，统计学上与 noop 无显著劣变**）
- `find_replace_seq vs rewrite_seq`：Δ = -0.0012 [-0.0019, -0.0006]（find_replace 显著优于 rewrite）
- `find_replace_seq vs swe_edit_seq`：Δ = -0.0043 [-0.0075, -0.0017]（find_replace 显著优于 swe_edit）
- `patch_seq vs rewrite_seq`：Δ = -0.0004 [-0.0016, +0.0009]（统计平手，但 patch 输出 tokens 少 22.7%）
- `patch_seq vs swe_edit_seq`：Δ = -0.0034 [-0.0070, -0.0006]（patch 显著优于 swe_edit）

官方聚合口径（`score_all`）：
| arm | cMER micro ↓ | cMER macro ↓ | wMER macro ↓ | Pref Score (cMER) ↑ |
|---|---|---|---|---|
| noop | **0.0036** | **0.0040** | **0.0233** | **+0.0000** |
| find_replace_seq | 0.0055 | 0.0050 | 0.0225 | **-0.2727** |
| patch_seq | 0.0058 | 0.0059 | 0.0350 | -0.4545 |
| rewrite_seq | 0.0069 | 0.0062 | 0.0254 | -0.5455 |
| swe_edit_seq | 0.0089 | 0.0093 | 0.0326 | -1.0000 |

## 读法与结论

1. **单机会局部约束（Local Scope）显著压制了过修，`find_replace_seq` 最稳健**：
   - 相比于允许全局跨 chunk 回溯编辑的 `dta19-seq-global`，单机会（禁止跨 chunk 回溯）限制了模型的修改触手，`find_replace_seq` 达成所有实验组中的最高保真度（cMER 0.0050，过修率 broken 仅 0.27%，幻觉率仅 0.20%）；
   - 与 `noop` 的配对差异仅为 +0.0010，95% CI [-0.0002, +0.0022] 跨过 0，是连续序列修复中唯一与 noop 达成统计平手的方案。
2. **`patch_seq` 注意力聚焦效应显著提升修错召回**：
   - 在局部作用域下，模型每一轮只面对当前 chunk 的独立局部 ID（b1 起排），其修错召回率（fixed_rate）从全局回溯时的 33.99% 跃升至 **42.98%**，且 cMER 优化至 0.0059；
   - 同时，`patch_seq` 保持了全场最低的输出 Token 开销（746.7k，比 rewrite 少 22.7%）。
3. **`rewrite_seq` 多轮长上下文累积导致截断与资源浪费**：
   - 虽然局部重写的 cMER（0.0062）优于单 chunk 独立 session（0.0127），但多轮历史使得上下文逐步膨胀，导致 1 个 session 发生 `incomplete` 截断；
   - 其输出 Token 消耗高达 966.2k，证明在流式连续场景下重写整段依然是高成本且脆弱的范式。
4. **`swe_edit_seq` 在单轮局部行号下依然垫底**：
   - 即使每轮将行号从 1 重置，swe_edit 在缺乏即时交互报错的环境下，行号误判率依旧居高不下（broken 0.70%，cMER 0.0093），在官方偏好胜率上 11 篇文档全输（Pref Score -1.0000）。

## 资产与备注

- 报告：`runs/dta19-seq-local/report.json`；磁带：`runs/dta19-seq-local/sessions/`
- 数据集规模：`dta19-l0` dev split 共 11 篇文档，每篇文档包含 10 个 chunk（对话轮数 = 10，总 session = 11 × 5 = 55）。
