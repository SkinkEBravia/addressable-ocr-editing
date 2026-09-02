# 实现现状（对照新设计 08–11）

> 描述性文档，随重写推进更新；规范以 Design/ 各篇为准。只记要点。

## 已有（设计框架内）

**IR 核心（01–07）**：sourceio / partition / ir（CAS store）/ reconstruction / view / surface 全部实现，与文档一致；链式叠加已修（坑 #1）。CLI（`doc ingest/view/patch/write/rollback`）可用。

**AgentID 策略**：`blockkey-as-is`——`AgentBlockId = BlockKey`，未实现第二套策略。标注形式 `xml-ish`。

**方言 `fn`**：一行一调用、全位置参数、JSON 字符串、裸标识符（`HEAD`）、`#` 注释、行号定位、`ParseError` 带行号；受控 JSON 解析，无 eval。

**LLM（08 对应）**：`complete(messages)` 消息列表签名；三协议适配器齐备
（openai-response / anthropic / openai-completion，优先级见 08），golden 测试覆盖；
`Usage` 含 `reasoning_tokens`；anthropic 口径 input_tokens = 端点三字段求和
（含 cache_read，与 OpenAI 系 prompt_tokens 对齐）。

**工具与 loop（09 对应）**：loop + ToolSet 契约 + Budget；标准集
noop / rewrite / rewrite_pieces / patch / find_replace；组装规则 =
system（instruction + prompt_clause）+ user（输入呈现），共用
`build_initial_messages`；错误即反馈。

**数据集（10 对应）**：loader 注册表契约（`<subset>/<language>/<granularity>`），
组合权在调用方（datasetkit.resolve = 选 key + chain + ids/limit）；
tiny 与 hipe_2026 同过一份契约测试。

**实验（11 对应）**：`--loaders` 选择；对话录逐轮增量落盘；resume 键含配置哈希；
报告含 token 构成；RichProgress 流式 TPS（delta 只计数不预览）。

## 缺口（重写要解决什么）

| 设计 | 现状 | 缺口 |
|---|---|---|
| 07 MCP | 无 | `doc serve`（Streamable HTTP） |
| 09 外部 harness | 无 | codex 式工具集 / run_external（v2） |
