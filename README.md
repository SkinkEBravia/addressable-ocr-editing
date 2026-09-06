# Batch-Doc-Process-V2

OCR 后矫正（post-correction）实验框架：同一份任务、同一个模型，比较不同**工具配置**（noop / rewrite / patch / find_replace / *_seq …）的指标与 token 成本。

## 跑一个实验（不用看代码）

```bash
# 1. 装依赖（uv，https://docs.astral.sh/uv/）
uv sync

# 2. 写 .env（项目根，二选一或都写）
#    VOLCENGINE_API_KEY=...     # 火山引擎 ark（glm-5.3-flash / volc-deepseek-v4-flash）
#    DEEPSEEK_API_KEY=...       # DeepSeek 官方（deepseek-v4-flash）

# 3. 跑：1 篇英文文档 × 3 个工具配置
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite,patch --model volc-deepseek-v4-flash \
    --split dev --loaders icdar2017/en/doc \
    --ids "icdar2017/periodical__eng_periodical-5" \
    --out runs/my-first --workers 4
```

跑完看两样东西：

```text
runs/my-first/report.json    # 指标（cmer）、token 构成、配对比较、失败明细（failure 段）
runs/my-first/sessions/      # 磁带：每个 cell 的完整对话（可审计、可 replay）
```

常用变体：

```bash
# 选子集：--loaders <子集/语言/粒度> 组合，--ids-from meta:key=value 过滤，--limit 截断
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite --model glm-5.3-flash \
    --split dev --loaders icdar2017/en/chunk --limit 5 --out runs/quick5

# 断点续跑：同一命令重跑即可（done 跳过、failed 重试、中断重跑该 cell）
# 改了后处理（方言解析 / 工具 fold / extract / 评分）？磁带重放，不重打 API：
uv run python -m experiment --out runs/my-first --replay
# replay 时替换某工具配置的 fold 行为（确定性后处理替换件，如换应用策略）：
uv run python -m experiment --out runs/my-first --replay --replay-with patch=patch-lenient
# 只重建报告：
uv run python -m experiment --out runs/my-first --report-only
```

`--workers N` 并发路数（默认 1）；`--no-stream` 关流式观察。失败类别直接写在
report 的 `failure` 段（`rejected` / `incomplete` / `timeout` …，含 http_status 与现场细节）。

## 架构一句话

```text
组装上下文 → agent loop（Session，逐轮落盘磁带）→ 工具 fold → SourceText → 评测
```

四个阶段各有公开契约，模块间只经契约交互。详见 [Docs/Design/00-dataflow.md](Docs/Design/00-dataflow.md)。

## 替换与开发组件

| 要换什么 | 怎么做 | 契约文档 |
|---|---|---|
| 模型 / 端点 | `configs/models/*.toml` 加一个文件（protocol / base_url / key_env / 采样键）；新协议加一个 `llm` 适配器 | [08-llm](Docs/Design/08-llm.md) |
| 工具配置 | `configs/toolsets/*.toml` 加一个文件：`toolset` + `max_turns` / `token_budget`，patch 系另有 `apply_mode`（atomic / best_effort）与 `hide_ops` | [09-tools](Docs/Design/09-tools.md) |
| 工具集 | 实现 `ToolSet` 契约五件套（`make_tool_state` / `present_input` / `parse` / `invoke` / `extract`），注册进 `agent.REGISTRY` | [09-tools](Docs/Design/09-tools.md) |
| 数据集 | 一个目录 + 一个 `dataset.py`（`loaders` / `scorer` / `default_instruction` / `info` 四入口），过同一份契约测试 | [10-datasets](Docs/Design/10-datasets.md) |
| 运行时报告器 | `--reporter module:Class` 挂自研实现（观察回调，不影响语义） | [11-experiment](Docs/Design/11-experiment.md) |
| patch 应用策略 | `run_patch(..., mode=)`；atomic 整批回滚 / best_effort 逐条跳过失败 op | [07-agent-api](Docs/Design/07-agent-api.md) |

内置工具集：`noop`（锚点）、`rewrite`（单轮全文重写）、`patch`（IR 块补丁，多轮反馈）、
`find_replace`（字符串锚最小复刻）、`swe_edit`（行号锚，经典 SWE-agent 复刻）、
`swe_bash`（SWE 环境忠实复刻：bash + PATH 上的 edit 脚本，本机 Git Bash 后端）、
`rewrite_seq` / `patch_seq`（逐 chunk 顺序修复，一文档一场对话，无反馈口径）。

## 工具集命名

```text
<寻址机制>[_<操作子集>][_<作用域>]
```

| 段 | 取值 | 省略时 |
|---|---|---|
| 寻址机制 | `rewrite` / `patch` / `swe_edit` / `find_replace` | — |
| 操作子集 | 如 `replace` | **全集** |
| 作用域 | `local_seq`（每轮一个单元，只改当前）/ `global_seq`（可回溯改历史单元） | **单轮**（全部输入一次给出） |

规矩：**凡是改变模型可见操作面的差异，必须体现在注册表键上**，不能只靠 toml
文件名区分。只有当系统**真正拒绝**白名单外操作时才可加操作子集后缀 ——
`hide_ops` 只裁剪提示词、不拦截操作，据它命名会让名字撒谎
（见 [Docs/Design/09-tools.md](Docs/Design/09-tools.md)）。

> [!WARNING]
> **历史包袱**：`rewrite_seq` / `patch_seq` / `swe_edit_seq` / `find_replace_seq`
> 是旧命名，等价于对应的 `*_local_seq`，**仅为读回既有 run 保留，勿用于新实验**。
>
> 不能直接删除：工具集名进入 **resume 键**、**磁带路径**
> （`sessions/<task_id>/<toolset>.json`）与 **report 的 arm 键** —— 删掉会让
> 既有 run 无法 `resume` / `--replay` / `--report-only`。

## 测试

```bash
uv run pytest          # 离线测试（含 configs/ 一致性冒烟）；真实 API 冒烟用 -m live
```

## 容器（Docker）

根目录 `Dockerfile` 构建的实验镜像：依赖全预装（venv 在 `/opt`），代码/配置/数据/runs 经 bind mount 与宿主同步——**改代码不用更新容器，挂载即生效**。

```powershell
# 构建（代码变动不需要重建；只有 pyproject/uv.lock 变了才重建）
docker build -t bdpc-exp .

# 进容器交互式实验（.env 经 --env-file 注入，不进镜像）——PowerShell：
docker run --rm -it --env-file .env `
  -v ${PWD}/src:/app/src -v ${PWD}/configs:/app/configs `
  -v ${PWD}/datasets:/app/datasets -v ${PWD}/runs:/app/runs `
  -v ${PWD}/tests:/app/tests bdpc-exp
```

```bash
# 进容器——Git Bash（必须加 MSYS_NO_PATHCONV=1，否则 -v 的 /app 被路径转换吃掉）：
MSYS_NO_PATHCONV=1 docker run --rm -it --env-file .env \
  -v ${PWD}/src:/app/src -v ${PWD}/configs:/app/configs \
  -v ${PWD}/datasets:/app/datasets -v ${PWD}/runs:/app/runs \
  -v ${PWD}/tests:/app/tests bdpc-exp
```

```bash
# 容器内：命令与宿主完全一致
uv run python -m experiment --dataset datasets/hipe_2026 \
    --toolsets noop,rewrite,patch --model volc-deepseek-v4-flash \
    --split dev --loaders icdar2017/en/doc --out runs/my-first --workers 4
```

磁带与报告直接写回宿主 `runs/`；容器内 bash 原生可用（swe_bash 后端在 Linux 下与 Windows Git Bash 行为一致）。

## 设计文档

从 [Docs/Design/00-dataflow.md](Docs/Design/00-dataflow.md) 的文档索引进；
实现现状与已验证口径（含火山端点的坑）见 [Docs/impl-status.md](Docs/impl-status.md)。
