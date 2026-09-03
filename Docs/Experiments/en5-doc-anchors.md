# en5-doc-anchors

> 状态：待跑

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

### bash（容器内）

```bash
docker run --rm --env-file .env \
  -v $PWD/src:/app/src -v $PWD/configs:/app/configs \
  -v $PWD/datasets:/app/datasets -v $PWD/runs:/app/runs \
  bdpc-exp uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,find_replace,swe_edit --model volc-deepseek-v4-flash \
    --split dev --loaders icdar2017/en/doc \
    --ids "icdar2017/periodical__eng_periodical-5" \
    --out runs/en5-doc-anchors --workers 3
```

## 结果

（跑完填）

## 读法与结论

（跑完填）

## 资产与备注

- 报告：`runs/en5-doc-anchors/report.json`；磁带：`runs/en5-doc-anchors/sessions/`
- patch 臂的多轮对照取 `en5-doc-patch8t`（同模型配置、同文档、同 8 轮预算），不在本 run 内重复。
- 首轮均注入完整 doc（上下文管理与 rewrite 一致，只有工具不同）。
