# 实现现状

> 描述性文档，随重写推进更新；规范以 Design/ 各篇为准。只记要点。

## 已有（设计框架内）

**IR 核心（01–07）**：sourceio / partition / ir（CAS store）/ reconstruction / view / surface 已实现；本轮补齐严格分区入口、Append 块坯接口、最终 View 内容哈希，以及回执构建与属性累计。CLI 通过 `python -m application` 调用 ingest/view/patch/write/rollback，未注册 doc 可执行入口。深层不可变与完整加载校验仍按 03／05 说明的边界处理。

**AgentID 策略**：已有 blockkey_as_is、numkey、line_number 等策略；标注已有 xml_ish、cat_n、plain 等，详见 06。

**方言 `fn`**：一行一调用、全位置参数、JSON 字符串、裸标识符（`HEAD`）、`#` 注释、行号定位、`ParseError` 带行号；受控 JSON 解析，无 eval。

**LLM（08）**：已[迁移到 LiteLLM Python SDK 1.106.0](Design/08-llm.md#litellm-接入方案)，旧自建适配器移除。保留 `complete(messages, on_delta=None) → Completion` 与配置／Failure 接口；三协议用实际 SDK 加 mock HTTP 验证。Tenacity 执行包含流式消费的唯一重试预算，SDK 重试关闭。空回答、failed 状态与中途断连不再静默成功；服务端缺少 usage 时保留 None，Anthropic 输入计数包含缓存读取／创建。

本轮 DeepSeek 真实流式冒烟通过；Responses 与 Anthropic 只做离线验证。固定 SDK 版本的用量保留钩子与导入依赖说明见 08，完整执行结果见[本轮记录](../plan/known-fixes-execution.md)。

**Agent（09，本轮重写，旧 toolsets 包废除）**：`Session` = 运行时状态与磁带一体（turns 追加式；usage 派生；`failure` 挂在 Session 上，turn-0 失败也有完整现场；`tool_state` 工具集私有不落盘）；上下文组装单一入口（`build_initial_messages`）；loop 三通道错误处理（对话 / 重试 / 失败），工具意外异常记 `Failure(stage="tool")` 不喂模型；extract 出口 = `SourceText`（签名 `(tool_state, session)`）。标准集：noop / rewrite / patch / find_replace / rewrite_seq / patch_seq / swe_edit / swe_bash。patch 支持可替换应用策略（`apply_mode = atomic | best_effort`，见 07「应用策略」）与提示词操作清单裁剪（`hide_ops`）；replay 支持 `--replay-with` 覆盖 fold 行为。swe_edit 构建在 IR 之上（partition_lines + `line_number` 策略 + `cat_n` 标注，见 06 配套表）；swe_bash 环境 = text.txt + bin/edit + bin/replace 脚本（GitBashBackend）。

**数据集（10）**：未动。loader 注册表契约（`<subset>/<language>/<granularity>`），组合权在调用方（datasetkit.resolve = 选 key + chain + ids/limit）；tiny 与 hipe_2026 同过一份契约测试。

**实验（11，本轮重写）**：`SessionStore` 磁带落盘 `sessions/<task_id>/<toolset>.json`（逐轮原子重写，messages 哈希去重，version 字段）；resume = (task_id, toolset, config_hash)，failed/running 一律重跑；CLI 同旧口径 + `--no-stream`（流式为显式运行参数，不再嗅探报告器）；报告含 token 构成、配对比较、failure 按 kind 聚合；replay 重 fold 磁带（tool_state 重建，output 变更记 changed/lower_bound）。

## 缺口（重写要解决什么）

| 设计 | 现状 | 缺口 |
|---|---|---|
| 07 MCP | 无 | 拟议 serve 接口与子命令（Streamable HTTP），当前未实现 |
| 09 外部 harness | 无 | codex 式工具集 / run_external（v2） |
| 09 多对话变体 | rewrite_pieces 未迁移 | 由组装层一任务多 Session 实现，待需要时加 |

## 验证

当前回归和小规模真实测试以[本轮执行记录](../plan/known-fixes-execution.md)为准。以下保留此前重写阶段的历史验证，不代表当前测试总数。

```text
tests/ 284 passed（01-07 与数据集契约 255 个保留测试 + 新 llm/agent/experiment 29 个）
volc-deepseek-v4-flash doc 粒度实证（runs/probe-en5-doc）：
  原 failed:bad_response 的真身 = failed:incomplete——端点 200 返回
  status=incomplete, incomplete_details.reason="length"，零可见输出。
  根因：output_length 在 openai-response 协议下原为「信息性」从不下发，
  端点默认输出上限 ≈32k（模型能力 384k），长输出任务被默认预算截断。
  修复：显式 output_length 一律下发为 max_output_tokens / max_tokens
  （08 文档语义已同步）；修复后实证见 runs/en5-doc-1t。
```


