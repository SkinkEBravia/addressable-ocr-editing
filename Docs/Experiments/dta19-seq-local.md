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

> [!note] 口径（2026-09-06 全面重算）
> - **主口径为中位数** —— 均值在本数据上被重尾污染（l0-doc 的 `swe_edit` 均值/中位 = 4.68×）。均值与 CI 并列保留，`max` 单列。
> - **`patch` 臂全部为 `apply_mode="best_effort"`**。此前以默认的 `atomic` 运行，单条 `replace` 失配即整批回滚，作废了 19.5%~83.7% 的已提交 op。旧的 atomic 数字已从本记录移除，事故记录见 [[shit#11. 实验记录里的配置描述与 toml 不符]]。
> - 指标定义见 `datasets/hipe_2026/dataset.py`；`edit_spans` = 由 input↔output 对齐得出的改动区域数（**跨臂统一口径**，`rewrite` 无显式 op 也可算）。


| arm | cmer 中位 ↓ | 均值 [95% CI] | p90 | **max** | fixed ↑ | broken ↓ | halluc ↓ | edit_spans | out tok | reasoning |
|---|---|---|---|---|---|---|---|---|---|---|
| `noop` | **0.0037** | 0.0040 [0.0031, 0.0052] | 0.0060 | **0.0081** | 0.00% | 0.00% | 0.00% | 0.0 | 0.0k | — |
| `rewrite_seq` | **0.0061** | 0.0062 [0.0048, 0.0078] | 0.0095 | **0.0115** | 44.05% | 0.41% | 0.29% | 53.7 | 966.2k | 93.6% |
| `patch_seq` | **0.0059** | 0.0059 [0.0047, 0.0071] | 0.0089 | **0.0096** | 42.98% | 0.36% | 0.27% | 52.5 | 746.7k | 98.6% |
| `swe_edit_seq` | **0.0057** | 0.0093 [0.0061, 0.0128] | 0.0156 | **0.0230** | 41.82% | 0.70% | 0.40% | 59.8 | 986.7k | 97.9% |
| `find_replace_seq` | **0.0048** | 0.0050 [0.0037, 0.0063] | 0.0078 | **0.0093** | 41.40% | 0.27% | 0.20% | 43.2 | 779.6k | 98.3% |

**破坏的 S/D/I 分解**（每单元平均字符数）：

| arm | broken_sub（改错） | broken_del（漏抄） | broken_ins（幻觉插入） | del 占比 |
|---|---|---|---|---|
| `rewrite_seq` | 8.0 | 6.8 | 52.4 | 10.1% |
| `patch_seq` | 6.0 | 5.5 | 39.9 | 10.8% |
| `swe_edit_seq` | 25.7 | 11.2 | 57.5 | 11.8% |
| `find_replace_seq` | 4.6 | 4.7 | 37.7 | 10.0% |

## 读法与结论

1. **单机会局部作用域：四臂全部不敌 noop，但差距被压得很小**
   - 中位：`noop` **0.0037** < `find_replace_seq` 0.0048 < `swe_edit_seq` 0.0057 < `patch_seq` 0.0059 < `rewrite_seq` 0.0061。
   - `find_replace_seq` 与 noop 的配对差 +0.0010 [−0.0002, +0.0022] **CI 跨 0** —— 连续序列修复中唯一与 noop 打平的方案。

2. **原「`swe_edit_seq` 垫底」的结论作废 —— 那是均值口径的误读**
   - 均值下 `swe_edit_seq` 0.0093 确实最差；但**中位 0.0057 排第二好**，仅次于 `find_replace_seq`。
   - 均值/中位 = 1.63×，仍是本 run 重尾最重的臂（max 0.0230），但**典型表现并不差**。

3. **局部作用域把尾部钉住了**（与 `dta19-doc-1t` 对照）

   | `swe_edit` 所在形态 | 中位 | max | 均值/中位 |
   |---|---|---|---|
   | doc 单轮 | 0.0062 | **0.2579** | 4.68× |
   | **seq-local** | 0.0057 | **0.0230** | 1.63× |

   - 中位几乎不变，**max 降了 11 倍**。每轮只呈现一个单元、行号每单元重排 ⇒ 一次误编辑最多毁掉一个单元。
   - ⇒ **作用域隔离买到的是尾部安全，不是平均质量。**

4. **`patch_seq` 的召回随局部聚焦提升**：每轮只面对当前单元的独立块 id，`fixed` 达 42.98%（全局回溯下为 33.99%），且输出 token 最低（746.7k，较 `rewrite_seq` 少 22.7%）。

5. **`rewrite_seq` 的多轮上下文累积代价**：1 个 session 触发 `incomplete`；输出 token 966.2k 为全场最高。


## 资产与备注

- 报告：`runs/dta19-seq-local/report.json`；磁带：`runs/dta19-seq-local/sessions/`
- 数据集规模：`dta19-l0` dev split 共 11 篇文档，每篇文档包含 10 个 chunk（对话轮数 = 10，总 session = 11 × 5 = 55）。
