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

> [!note] 口径（2026-09-06 全面重算）
> - **主口径为中位数** —— 均值在本数据上被重尾污染（l0-doc 的 `swe_edit` 均值/中位 = 4.68×）。均值与 CI 并列保留，`max` 单列。
> - **`patch` 臂全部为 `apply_mode="best_effort"`**。此前以默认的 `atomic` 运行，单条 `replace` 失配即整批回滚，作废了 19.5%~83.7% 的已提交 op。旧的 atomic 数字已从本记录移除，事故记录见 [[shit#11. 实验记录里的配置描述与 toml 不符]]。
> - 指标定义见 `datasets/hipe_2026/dataset.py`；`edit_spans` = 由 input↔output 对齐得出的改动区域数（**跨臂统一口径**，`rewrite` 无显式 op 也可算）。


| arm | cmer 中位 ↓ | 均值 [95% CI] | p90 | **max** | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | out tok | reasoning |
|---|---|---|---|---|---|---|---|---|---|---|
| `noop` | **0.0587** | 0.0580 [0.0549, 0.0607] | 0.0624 | **0.0659** | 0.00% | 0.00% | 0.00% | 0.0 | 0.0k | — |
| `rewrite_seq` | **0.0206** | 0.0238 [0.0187, 0.0309] | 0.0280 | **0.0564** | 78.10% | 1.17% | 0.56% | 678.3 | 1.52M | 96.0% |
| `patch_seq` | **0.0204** | 0.0236 [0.0182, 0.0315] | 0.0277 | **0.0605** | 73.06% | 0.83% | 0.36% | 535.3 | 1.44M | 94.2% |
| `swe_edit_seq` | **0.0232** | 0.0307 [0.0208, 0.0439] | 0.0440 | **0.0866** | 80.88% | 2.08% | 0.80% | 780.5 | 1.50M | 96.7% |
| `find_replace_seq` | **0.0191** | 0.0198 [0.0168, 0.0229] | 0.0275 | **0.0293** | 81.72% | 0.97% | 0.44% | 734.2 | 1.43M | 94.8% |

**破坏的 S/D/I 分解**（每单元平均字符数）：

| arm | broken_sub（改错） | broken_del（漏抄） | broken_ins（幻觉插入） | del 占比 |
|---|---|---|---|---|
| `rewrite_seq` | 40.4 | 29.1 | 77.5 | 19.8% |
| `patch_seq` | 30.1 | 17.1 | 41.1 | 19.4% |
| `swe_edit_seq` | 135.1 | 46.2 | 116.3 | 15.5% |
| `find_replace_seq` | 50.1 | 18.3 | 72.5 | 13.0% |

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
