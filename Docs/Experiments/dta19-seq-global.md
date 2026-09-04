# dta19-seq-global

> 状态：待跑

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

| arm | status | cmer ↓ | fixed ↑ | missed ↓ | broken ↓ | halluc ↓ | tokens in/out | reasoning 占比 |
|---|---|---|---|---|---|---|---|---|
| noop | done | 待跑 | 0.0% | 100.0% | 0.0% | 0.0% | 0 / 0 | — |
| patch_global_seq | 待跑 | | | | | | | |
| swe_edit_global_seq | 待跑 | | | | | | | |
| find_replace_global_seq | 待跑 | | | | | | | |

## 读法与结论

（待实验运行后补充）

## 资产与备注

- 报告：`runs/dta19-seq-global/report.json`；磁带：`runs/dta19-seq-global/sessions/`
- 数据集规模：`dta19-l0` dev split 共 11 篇文档，11 × 4 = 44 个 session。
- 严格剔除 rewrite：根据设计，rewrite 没有局部寻址与跨文件修改能力。
