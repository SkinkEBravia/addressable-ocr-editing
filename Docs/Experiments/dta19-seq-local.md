# dta19-seq-local

> 状态：待跑

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

| arm | status | cmer ↓ | fixed ↑ | missed ↓ | broken ↓ | halluc ↓ | tokens in/out | reasoning 占比 |
|---|---|---|---|---|---|---|---|---|
| noop | done | 待跑 | 0.0% | 100.0% | 0.0% | 0.0% | 0 / 0 | — |
| rewrite_seq | 待跑 | | | | | | | |
| patch_seq | 待跑 | | | | | | | |
| swe_edit_seq | 待跑 | | | | | | | |
| find_replace_seq | 待跑 | | | | | | | |

## 读法与结论

（待实验运行后补充）

## 资产与备注

- 报告：`runs/dta19-seq-local/report.json`；磁带：`runs/dta19-seq-local/sessions/`
- 数据集规模：`dta19-l0` dev split 共 11 篇文档，每篇文档包含 10 个 chunk（对话轮数 = 10，总 session = 11 × 5 = 55）。
