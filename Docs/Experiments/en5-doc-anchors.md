# en5-doc-anchors

> 状态：已完成（2026-09-04）

## 问题

锚点类型三方对比：同样的多轮反馈 loop（8 轮）、同样的 doc，块 id 锚 / 字符串锚 / 行号锚哪种对模型最友好、修复效率最高？产出每 arm 的 cmer × 轮数 曲线（多少轮追上单发 patch/rewrite）。

## Arms

| arm | 形态 | 说明 |
|---|---|---|
| noop | 锚点 | 不调 LLM，no-correction 基线 |
| find_replace | 字符串锚 | `read` / `find_replace(old, new)`，replace-all 语义（Aider / Claude Code Edit 流派） |
| swe_edit | 行号锚 | `view` / `edit(start, end, "text")`，IR 行号操作面（partition_lines + line_number + cat_n） |

## 命令

### PowerShell（宿主）

```powershell
uv run python -m experiment --dataset datasets/hipe_2026 `
    --toolsets noop,find_replace,swe_edit --model volc-deepseek-v4-flash `
    --split dev --loaders icdar2017/en/doc `
    --ids "icdar2017/periodical__eng_periodical-5" `
    --out runs/en5-doc-anchors --workers 3
```

### bash（容器内，先经 README「容器」节的 docker run 进入）

```bash
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,find_replace,swe_edit --model volc-deepseek-v4-flash \
    --split dev --loaders icdar2017/en/doc \
    --ids "icdar2017/periodical__eng_periodical-5" \
    --out runs/en5-doc-anchors --workers 3
```

## 结果

**终局（cmer ↓）**

| arm | status | cmer | Δ vs noop | out tokens | reasoning 占比 |
|---|---|---|---|---|---|
| noop | done | 0.0928 | — | 0 | — |
| swe_edit | done（3 轮） | 0.0353 | -0.0576 | 71.9k | 89.1% |
| find_replace | budget_exceeded（8 轮） | 0.0362 | -0.0567 | 163.6k | 90.7% |

**cmer × 轮数（逐轮重放磁带；turn 0 = 未修复基线）**

| turn | swe_edit | find_replace |
|---|---|---|
| 0 | 0.0928 | 0.0928 |
| 1 | 0.0928（整段 parse 失败，59k token 作废） | 0.0928（首次替换无净变更，96k token） |
| 2 | 0.0353（11 条 edit 一把梭，全部生效） | 0.0378 |
| 3 | done()（118 tok 收工） | 0.0378 |
| 4 | — | 0.0357 |
| 5-6 | — | 0.0356（平台期） |
| 7-8 | — | 0.0362（轻微回退，预算耗尽） |

对照参照线：单发 patch 0.0346（en5-doc-1t）、单发 rewrite 0.0473、patch_seq 0.0325（en5-seq）。

## 读法与结论

- **行号锚对模型最友好**：swe_edit 第二轮就一把 11 条 edit 全部生效、第三轮收工，72k out token 达到与单发 patch 同级质量，是反馈臂里最省钱的。
- 字符串锚同质量但 2.3 倍 token（163.6k），且后 4 轮平台期+轻微回退（过度编辑）。
- 两个锚点首轮都「先交一次学费」（parse 失败 / 无效替换）再靠反馈自愈——这正是多轮口径的意义；单轮下这些错误全是零变更。
- 结论：**swe_edit ≈ find_replace ≈ 单发 patch（质量），swe_edit 成本最优**；块 id 锚的多轮对照已补齐（en5-doc-patch8t：patch 1 轮 0.0312 / 67.9k，三锚点双优居首）。

## 资产与备注

- 报告：`runs/en5-doc-anchors/report.json`；磁带：`runs/en5-doc-anchors/sessions/`
- swe_edit 首轮 parse_error 原因：模型把 11 条 edit 和 done() 写在同一消息（条款要求 done() 单独成消息）——反馈一轮即自愈。
- 逐轮 cmer 由离线重放磁带 fold 产出（确定性后处理，未重打 API）。
