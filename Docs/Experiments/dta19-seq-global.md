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

> [!note] 口径（2026-09-06 全面重算）
> - **主口径为中位数** —— 均值在本数据上被重尾污染（l0-doc 的 `swe_edit` 均值/中位 = 4.68×）。均值与 CI 并列保留，`max` 单列。
> - **`patch` 臂全部为 `apply_mode="best_effort"`**。此前以默认的 `atomic` 运行，单条 `replace` 失配即整批回滚，作废了 19.5%~83.7% 的已提交 op。旧的 atomic 数字已从本记录移除，事故记录见 [[shit#11. 实验记录里的配置描述与 toml 不符]]。
> - 指标定义见 `datasets/hipe_2026/dataset.py`；`edit_spans` = 由 input↔output 对齐得出的改动区域数（**跨臂统一口径**，`rewrite` 无显式 op 也可算）。


| arm | cmer 中位 ↓ | 均值 [95% CI] | p90 | **max** | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | out tok | reasoning |
|---|---|---|---|---|---|---|---|---|---|---|
| `noop` | **0.0037** | 0.0040 [0.0031, 0.0052] | 0.0060 | **0.0081** | 0.00% | 0.00% | 0.00% | 0.0 | 0.0k | — |
| `patch_global_seq` | **0.0051** | 0.0060 [0.0044, 0.0079] | 0.0106 | **0.0128** | 33.99% | 0.34% | 0.27% | 45.5 | 861.7k | 98.2% |
| `swe_edit_global_seq` | **0.0094** | 0.0097 [0.0072, 0.0120] | 0.0150 | **0.0175** | 43.75% | 0.75% | 0.52% | 65.3 | 1.16M | 97.4% |
| `find_replace_global_seq` | **0.0058** | 0.0058 [0.0045, 0.0072] | 0.0085 | **0.0109** | 42.81% | 0.35% | 0.27% | 48.0 | 711.4k | 98.2% |

**破坏的 S/D/I 分解**（每单元平均字符数）：

| arm | broken_sub（改错） | broken_del（漏抄） | broken_ins（幻觉插入） | del 占比 |
|---|---|---|---|---|
| `patch_global_seq` | 4.1 | 4.9 | 51.6 | 8.1% |
| `swe_edit_global_seq` | 8.3 | 15.4 | 72.9 | 15.9% |
| `find_replace_global_seq` | 6.3 | 3.8 | 46.3 | 6.8% |

## 读法与结论

1. **全局回溯作用域：100% 任务交付（0 failure）**
   - 44 个 session 全部 `done`。相比单轮长文档 `patch-1turn` 的 3 例 `incomplete`，逐单元呈现 + 命名空间寻址消除了单轮输出压力。

2. **`find_replace_global_seq` 与 `patch_global_seq` 并列第一梯队**
   - 中位：`noop` **0.0037** < `patch_global_seq` 0.0051 < `find_replace_global_seq` 0.0058 < `swe_edit_global_seq` 0.0094。
   - 两者配对差 +0.0003 [−0.0007, +0.0014]，**统计学完全平手**；过修率均仅 ~0.34%。

3. **原「文件前缀寻址拯救了 `swe_edit`」的结论**：⚠️ **方向要改**

   `swe_edit` 跨形态（L0，同一批 11 篇文档）：

   | 形态 | 中位 | max | 均值/中位 |
   |---|---|---|---|
   | doc 单轮 | **0.0062** | 0.2579 | 4.68× |
   | seq-local | 0.0057 | 0.0230 | 1.63× |
   | **seq-global** | **0.0094** | **0.0175** | **1.03×** |

   - **中位数上 `seq-global` 是三者里最差的**（0.0094，比 doc 单轮差 1.5 倍）—— 原先说的「cMER 从 0.0289 骤降至 0.0097」是**均值口径的误读**：doc 单轮的 0.0289 由单篇灾难（破坏 3203 字符）撑起，其中位仅 0.0062。
   - 命名空间隔离真正做到的是 **把尾部压了 15 倍**（max 0.2579 → 0.0175），且几乎消除重尾（均值/中位 1.03×）。
   - ⇒ **正确说法：作用域隔离用中心趋势换尾部安全。** 行号作用域被限制在单个单元内，一次误编辑再也毁不掉整篇 —— 但每单元重排行号也切断了跨单元上下文，典型表现反而略差。

4. **全局 vs 局部的取舍**：`patch_global_seq` 的召回（33.99%）低于 `patch_seq`（42.98%），但官方 Preference Score 更稳健（−0.2727 vs −0.4545）—— 可回溯带来更少的极端负收益，代价是每轮的聚焦被稀释。


## 资产与备注

- 报告：`runs/dta19-seq-global/report.json`；磁带：`runs/dta19-seq-global/sessions/`
- 数据集规模：`dta19-l0` dev split 共 11 篇文档，11 × 4 = 44 个 session。
- 严格剔除 rewrite：根据设计，rewrite 没有局部寻址与跨文件修改能力。
