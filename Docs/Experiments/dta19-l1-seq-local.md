# dta19-l1-seq-local

> 状态：已完成（2026-09-05）

## 问题

在中等错误率德语子集（`dta19-l1`，官方基线 CMER 约 2.40%）上，流式连续 chunk 输入（Scope-Constrained 单机会，禁止跨 chunk 回溯）：
1. **中噪局部约束效果**：每篇文档 10 轮对话连续输入，每一轮仅允许对当前 chunk（独立行号与块 ID，从 1 编排）发起修复；
2. **修错与过修平衡**：检验在 2.4% 适中错误密度下，单机会局部作用域能否在提高修错召回率（fixed_rate）的同时，彻底隔绝历史跨轮干扰；
3. **工具横向对比**：对比 `patch_seq`、`find_replace_seq`、`swe_edit_seq` 与 `rewrite_seq` 在多轮渐进输入下的 cMER、Pref Score、输出 Token 与思考开销。

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
    --split dev --loaders dta19-l1/de/doc `
    --out runs/dta19-l1-seq-local --workers 11
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite_seq,patch_seq,swe_edit_seq,find_replace_seq \
    --model volc-deepseek-v4-flash \
    --split dev --loaders dta19-l1/de/doc \
    --out runs/dta19-l1-seq-local --workers 11
```

## 结果

> [!note] 口径（2026-09-06 全面重算）
> - **主口径为中位数** —— 均值在本数据上被重尾污染（l0-doc 的 `swe_edit` 均值/中位 = 4.68×）。均值与 CI 并列保留，`max` 单列。
> - **`patch` 臂全部为 `apply_mode="best_effort"`**。此前以默认的 `atomic` 运行，单条 `replace` 失配即整批回滚，作废了 19.5%~83.7% 的已提交 op。旧的 atomic 数字已从本记录移除，事故记录见 [[shit#11. 实验记录里的配置描述与 toml 不符]]。
> - 指标定义见 `datasets/hipe_2026/dataset.py`；`edit_spans` = 由 input↔output 对齐得出的改动区域数（**跨臂统一口径**，`rewrite` 无显式 op 也可算）。


| arm | cmer 中位 ↓ | 均值 [95% CI] | p90 | **max** | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | out tok | reasoning |
|---|---|---|---|---|---|---|---|---|---|---|
| `noop` | **0.0238** | 0.0242 [0.0229, 0.0257] | 0.0279 | **0.0284** | 0.00% | 0.00% | 0.00% | 0.0 | 0.0k | — |
| `rewrite_seq` | **0.0119** | 0.0122 [0.0102, 0.0140] | 0.0159 | **0.0177** | 83.03% | 0.82% | 0.49% | 334.0 | 1.29M | 93.1% |
| `patch_seq` | **0.0112** | 0.0149 [0.0107, 0.0195] | 0.0279 | **0.0284** | 54.40% | 0.34% | 0.21% | 166.7 | 1.05M | 95.3% |
| `swe_edit_seq` | **0.0118** | 0.0123 [0.0100, 0.0150] | 0.0201 | **0.0214** | 77.58% | 0.70% | 0.46% | 303.9 | 1.15M | 95.5% |
| `find_replace_seq` | **0.0098** | 0.0100 [0.0082, 0.0116] | 0.0133 | **0.0143** | 78.55% | 0.49% | 0.28% | 307.5 | 1.24M | 96.5% |

**破坏的 S/D/I 分解**（每单元平均字符数）：

| arm | broken_sub（改错） | broken_del（漏抄） | broken_ins（幻觉插入） | del 占比 |
|---|---|---|---|---|
| `rewrite_seq` | 16.4 | 24.4 | 77.2 | 20.7% |
| `patch_seq` | 6.9 | 4.9 | 23.2 | 14.0% |
| `swe_edit_seq` | 14.0 | 13.6 | 54.6 | 16.6% |
| `find_replace_seq` | 14.5 | 9.0 | 43.8 | 13.4% |

## 读法与结论

1. **`find_replace_seq` 斩获全场桂冠，突破至 1.00% 字符错误率**：
   - 在 10 轮流式连续输入下，`find_replace_seq` 将 cMER 从 0.0242 暴降至 **0.0100**（官方 Micro cMER 0.0102）；
   - 官方 Preference Score 达到满分 **+1.0000**（全部 11 篇文档 100% 优于 noop），且配对统计检验显著领先所有竞争方案（比 rewrite 净低 0.0022，比 swe_edit 净低 0.0023）；
   - 其过修率仅 0.49%、幻觉率仅 0.28%，展现了字符串字面锚在逐页递进修复时的超凡稳定性。
2. **多轮流式极大改善了 `rewrite` 和 `swe_edit` 的鲁棒性**：
   - 相比于整篇长文档单轮（`doc-1t`）面临的生成截断与脱靶风险，按页流式切分为 10 轮后，`rewrite_seq` 与 `swe_edit_seq` 的 Preference Score 也均达到了满分 **+1.0000**，cMER 双双稳定在 0.0122 附近；
   - 证明流式单机会隔离大幅降低了模型一次性处理万字文本的记忆负担。
3. **`patch_seq` 的块提取瓶颈**：
   - `patch_seq` 过修率依然最低（0.34%），但修错召回（54.40%）不如 find_replace（78.55%），且偶发 3 例标签提取异常，说明轻量级补丁方言在中度密集修错时的表达通畅度仍有优化空间。

## 资产与备注

- 报告：`runs/dta19-l1-seq-local/report.json`；磁带：`runs/dta19-l1-seq-local/sessions/`
- 数据集规模：`dta19-l1` dev split 共 11 篇文档，每篇文档 10 个 chunk（总计 11 × 5 = 55 个 session）。
- 对比参考：对比 `dta19-seq-local`（L0）与 `dta19-l1-doc-1t`（单轮整篇），评估单机会局部约束在不同错误密度下的通用泛化性。
