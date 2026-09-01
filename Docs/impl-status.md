# 实现现状（对照新设计 08–11）

> 描述性文档，随重写推进更新；规范以 Design/ 各篇为准。只记要点。

## 已有（设计框架内）

**IR 核心（01–07）**：sourceio / partition / ir（CAS store）/ reconstruction / view / surface 全部实现，与文档一致；链式叠加已修（坑 #1）。CLI（`doc ingest/view/patch/write/rollback`）可用。

**AgentID 策略**：`blockkey-as-is`——`AgentBlockId = BlockKey`，未实现第二套策略。标注形式 `xml-ish`。

**方言 `fn`**：一行一调用、全位置参数、JSON 字符串、裸标识符（`HEAD`）、`#` 注释、行号定位、`ParseError` 带行号；受控 JSON 解析，无 eval。

**LLM（08 对应）**：`LLMClient.complete(prompt, system=)` 单发签名；仅 deepseek 适配器（openai-completion 协议）；`Usage` 无 `reasoning_tokens`。

**实验（旧 08 对应）**：`experiment_app` 四通道单发 + 重试（无多轮 loop）；TOML 臂配置、replay、report 已有。

## 缺口（重写要解决什么）

| 设计 | 现状 | 缺口 |
|---|---|---|
| 08 `complete(messages)` | `complete(prompt, system=)` | 消息列表签名；`reasoning_tokens`；`ModelConfig` 装载；另两个协议适配器 |
| 09 loop / 工具集 | 四通道硬编码 runner | loop、`ToolSet` 契约、`Budget`；`find_replace` 配置；错误即反馈（替代重试预算） |
| 10 dataset 契约 | `datasets.py` 直读 HIPE jsonl | `dataset.py` 契约、`datasets/tiny/`、`evalkit`、scorer 归数据集 |
| 11 对话录 | raw 任务完成后才落盘；resume 键 = (样本, 臂名) | 逐轮增量落盘；resume 键含配置哈希；报告加 token 构成 |
| 07 MCP | 无 | `doc serve`（Streamable HTTP） |

## 重写顺序建议

llm 签名升级 → loop + 工具集（四通道迁入）→ dataset.py 契约（tiny + hipe）→ 对话录增量落盘与报告 → MCP / 外部 harness（v2）。
