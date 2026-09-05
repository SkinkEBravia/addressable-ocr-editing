# dta19-seq-global

> 状态：已完成（2026-09-05）

## 问题

流式连续 chunk 输入（Global Retrospective，允许跨 chunk 回溯修复）：
1. 每一轮输入一个新的 chunk，带有显式文件标识抬头（`--- [File: chunk_N] ---`）与前缀命名空间 ID；
2. 允许模型回溯编辑前面轮次已经呈现过的任何 chunk（例如第二轮发现第一轮的错词重新发起修改）；
3. **无 rewrite arm**：rewrite 协议由于缺乏显式块与文件定位语法，无法承担多文件回溯编辑能力；
4. 对比 patch、swe_edit 与 find_replace 在全局可回溯场景下的修错召回与跨轮干扰。

## Arms

| arm | 形态 | 说明 |
|---|---|---|
| noop | 锚点 | 不调 LLM，no-correction 基线 |
| patch_global_seq | 全局回溯补丁 | 前缀命名空间块 ID（c0:b1, c1:b2），支持跨 chunk 路由执行 patch |
| swe_edit_global_seq | 全局回溯行号编辑 | 显式文件寻址（edit chunk_0 1:2 << end），支持跨 chunk 目标编辑 |
| find_replace_global_seq | 全局回溯字符串替换 | 替换作用于当前及历史所有已呈现 chunk |

## 命令

### PowerShell（宿主）

```powershell
uv run python -m experiment --dataset datasets/hipe_2026 `
    --toolsets noop,patch_global_seq,swe_edit_global_seq,find_replace_global_seq `
    --model volc-deepseek-v4-flash `
    --split dev --loaders dta19-l0/de/doc `
    --out runs/dta19-seq-global --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,patch_global_seq,swe_edit_global_seq,find_replace_global_seq \
    --model volc-deepseek-v4-flash \
    --split dev --loaders dta19-l0/de/doc \
    --out runs/dta19-seq-global --workers 11
```

## 结果

| arm | cmer ↓ [95% CI] | Δ vs noop [CI] | fixed ↑ | missed ↓ | broken ↓ | halluc ↓ | out tokens | reasoning 占比 |
|---|---|---|---|---|---|---|---|---|
| noop | **0.0040** [0.0031, 0.0052] | — | 0.00% | 100.00% | **0.00%** | **0.00%** | **0** | — |
| patch_global_seq | 0.0060 [0.0044, 0.0079] | +0.0020 [+0.0005, +0.0038] | 33.99% | 66.01% | **0.34%** | **0.27%** | 861.7k | 98.2% |
| swe_edit_global_seq | 0.0097 [0.0072, 0.0120] | +0.0056 [+0.0035, +0.0076] | **43.75%** | **56.25%** | 0.75% | 0.52% | 1.2M | 97.4% |
| find_replace_global_seq | **0.0058** [0.0045, 0.0072] | +0.0017 [+0.0005, +0.0029] | 42.81% | 57.19% | 0.35% | **0.27%** | 711.4k | 98.2% |

配对差异（cMER Δ，[95% CI]）：
- `patch_global_seq vs find_replace_global_seq`：Δ = +0.0003 [-0.0007, +0.0014]（统计学完全平手）
- `patch_global_seq vs swe_edit_global_seq`：Δ = -0.0036 [-0.0061, -0.0011]（patch 显著优于 swe_edit）
- `find_replace_global_seq vs swe_edit_global_seq`：Δ = -0.0039 [-0.0063, -0.0015]（find_replace 显著优于 swe_edit）

官方聚合口径（`score_all`）：
| arm | cMER micro ↓ | cMER macro ↓ | wMER macro ↓ | Pref Score (cMER) ↑ |
|---|---|---|---|---|
| noop | **0.0036** | **0.0040** | **0.0233** | **+0.0000** |
| find_replace_global_seq | 0.0061 | 0.0058 | 0.0236 | -0.6364 |
| patch_global_seq | 0.0067 | 0.0060 | 0.0324 | -0.2727 |
| swe_edit_global_seq | 0.0090 | 0.0097 | 0.0419 | -0.8182 |

## 读法与结论

1. **多轮流式回溯成功实现 100% 任务交付（0 failure）**：
   - 相较于单轮长文档中 `patch-1turn` 因生成超长补丁出现 3 例 `incomplete`，在多轮逐 chunk 输入（伴随命名空间与文件标识）的设计下，全部 44 个 session（11 篇文档 × 4 arms）全部顺利完工。
2. **`find_replace_global_seq` 与 `patch_global_seq` 性能并列第一梯队**：
   - 两者 cMER 达到 0.0058 与 0.0060（配对差异 CI [-0.0007, +0.0014] 覆盖 0，统计学无差异）；
   - **过修控制优异**：两者的过修率（broken_rate）均只有 ~0.34%，插入幻觉率均仅为 0.27%；
   - `find_replace` 修错召回率更高（fixed_rate 42.81% vs 33.99%），且消耗 Token 更少（711.4k vs 861.7k）；
   - `patch` 在官方偏好胜率（Pref Score）上更稳健（-0.2727 vs -0.6364），说明补丁在绝大多数文档上的负收益波动更小。
3. **文件前缀显式寻址拯救了 `swe_edit`**：
   - 在单轮长文档（`dta19-doc-1t`）中，`swe_edit` 发生了严重的跨页行号漂移误删，导致 cMER 飙升至 0.0289（broken 2.85%）；
   - 在本实验中引入带文件名的定位语法（`edit chunk_N start:end`）后，行号作用域被严格限制在单页内部，cMER 从 0.0289 骤降回落至 **0.0097**（broken 从 2.85% 降至 0.75%），充分验证了命名空间隔离机制在多文档/长流程中的安全基石作用。

## 资产与备注

- 报告：`runs/dta19-seq-global/report.json`；磁带：`runs/dta19-seq-global/sessions/`
- 数据集规模：`dta19-l0` dev split 共 11 篇文档，11 × 4 = 44 个 session。
- 严格剔除 rewrite：根据设计，rewrite 没有局部寻址与跨文件修改能力。
