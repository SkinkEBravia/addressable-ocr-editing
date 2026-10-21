# LLM 客户端

> 无前置依赖；被 [09-tools.md](09-tools.md) 的 loop 驱动。

## 范围

`llm` 模块根据模型配置和聊天记录调用模型，输出统一的回答结果。它不解释 OCR 任务、编辑指令或工具调用，也不管理聊天历史。

替换底层客户端时，以本篇开头的输入输出接口与对外行为为不变量。协议实现、底层异常和重试机制放在后文说明。

## 输入输出接口

### 输入

| 输入 | 内容 | 提供方 |
|---|---|---|
| `ModelConfig` | 服务地址 base_url、API 协议 protocol、模型名 model、凭证变量名 key_env，以及生成和请求配置 | 调用方在构造客户端时提供 |
| API key | 根据 key_env 从进程环境变量读取的实际凭证 | llm 模块解析，不放入 Message |
| `list[Message]` | 本次请求的完整聊天记录，按顺序排列；每条消息包含 role（system／user／assistant）与 content（文本） | 调用方在每次 complete 时提供 |
| `on_delta` | 可选的文本片段回调，用于观察回答或推理内容的生成进度 | 调用方按需提供 |

### 输出

成功时返回一个 `Completion`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `text` | `str` | 模型的最终回答文本；不混入仅用于观察的推理片段 |
| `usage` | `Usage \| None` | 服务端返回的 token 用量；没有用量信息时为 None |
| `raw` | `JsonValue` | 用于审计和落盘的响应数据；具体来源在后文说明 |
| `elapsed_s` | `float \| None` | 整次调用的耗时，包含重试及等待；无法提供时为 None |

`Usage` 包含 input_tokens、output_tokens，以及可选的 reasoning_tokens。调用失败时抛出项目异常；模型访问失败通过 `LLMError.failure` 向上层提供可记录的 `Failure`，不把失败伪装成成功回答。

### 调用接口

```python
def build_client(config: ModelConfig) -> LLMClient: ...

class LLMClient(Protocol):
    def complete(
        self,
        messages: list[Message],
        *,
        on_delta: Callable[[str], None] | None = None,
    ) -> Completion: ...
```

### 替换时保持的约定

- 上层继续传入 ModelConfig 与 Message，接收 Completion 或项目异常；不接触 LiteLLM 的类型。
- 客户端不保存对话历史，不自动裁剪、补写或改写消息；上下文由调用方管理。
- 未提供 on_delta 时使用非流式调用；提供时使用流式调用。回调只用于观察，最终回答仍由 Completion.text 提供，两种方式采用相同的结果含义。
- 回答、用量和耗时维持原有含义：空回答不算成功，token 用量来自服务端，不能用本地估算补齐。
- 保留现有配置的含义与历史报告／磁带的可读性。失败信息仍可由上层记录，但不要求复制旧客户端的内部异常类型、异常文案或每一条错误映射；按调用方实际依赖处理必要兼容。

后续实现和验收首先验证这些约定。内部错误分类、重试算法及调试日志用于实现与排查，不单独作为保留自建客户端的理由。

## 定义

### `ModelConfig`

数据接口。一个可用模型的完整描述；TOML 一文件一模型，默认放 `configs/models/`，文件名即标签。

```toml
# configs/models/deepseek.toml
protocol        = "openai-completion"   # openai-completion | openai-response | anthropic
base_url        = "https://api.deepseek.com"
model           = "deepseek-chat"
key_env         = "DEEPSEEK_API_KEY"    # 环境变量名，间接引用
# 以下为可选配置项；参数发送规则和客户端默认值见下方说明
temperature     = 0.2
reasoning_effort = "low"                # low | medium | high
context_window  = 65536                 # 上下文窗口（信息性，暂不使用）
output_length   = 8192                  # 输出长度上限；显式值下发为 max_output_tokens / max_tokens
max_transport_retries = 3               # 重试通道上限
timeout         = 600.0                 # 请求超时设置；不等同于整个会话的总时限

# 端点专属参数（可选 TOML 表）：原样并入请求体顶层，核心字段（model/messages/
# input/采样键）后写、不可被它覆盖。用于 OpenRouter provider 路由等：
# [extra_body.provider]
# only = ["modal/fp8"]
# anthropic 适配器不支持本键：配置即 ConfigError（不静默忽略）。
```

规则：

- **未知键直接报错**（防拼写漂移）。
- `temperature` 与 `reasoning_effort` 可以不配置：未配置时不由对应配置字段向请求中添加该参数，使用服务端默认值。解析后的配置能区分“未配置”和“明确设置了值”；具体协议是否支持这些参数，见下方适配器规则。
- `context_window` 是声明性信息：供将来的历史管理与预算核算使用，不改变请求行为。
- `output_length` 是输出 token 数量上限：明确设置后，发送为 `max_output_tokens`（openai-response）/ `max_tokens`（openai-completion / anthropic）。anthropic 协议必须配置；其余两种协议可以不配置。长输出任务建议明确设置：服务端默认上限可能远低于模型能力（volc 实测默认 ≈32k，模型上限 384k），使用默认上限可能导致输出被截断成 `incomplete`。
- `max_transport_retries` 与 `timeout` 控制客户端的重试和等待行为，不作为模型生成参数发送；未配置时分别使用 3 次重试和 600 秒的超时设置。
- `extra_body` 是端点专属参数的透传口（如 OpenRouter 的 provider 路由）：并入请求体顶层，进入 `as_dict()` 序列化（即进 report.json 与 config_hash——同名配置改了 extra_body 视为新运行）；其内部内容不做校验，协议适配器不支持时报 ConfigError。
- 采样参数属于模型配置：同一实验内各工具配置共用同一模型配置（公平性，见 [11](11-experiment.md#公平性)）。

### 凭证

- key 只从环境变量读取。装配层在任何解析之前，先把项目根 `.env`（若存在）加载进进程环境，已有的进程环境变量优先，不被 `.env` 覆盖。解析得到的 key 作为本次调用参数传给 LiteLLM，不设置库的全局凭证。
- `.env` 与任何含 key 的文件必须 gitignore；配置、报告、磁带中只允许出现 `key_env` 的**名字**。
- `key_env` 未设置 ⇒ `CredentialError`，不发请求。
- API key 不进入任何异常消息与 Failure detail（安全约束）。

### `Message` / `Completion` / `Usage`

```python
Message = { role: "system" | "user" | "assistant", content: str }

Completion = { text: str, usage: Usage | None, raw: JsonValue, elapsed_s: float | None }
Usage = { input_tokens: int, output_tokens: int, reasoning_tokens: int | None }
```

- token 计数一律取自端点 `usage` 字段，**不做本地估算**；端点不返回时 `usage = None`，报告记 `usage_missing`。
- `reasoning_tokens` 单列：思考强度产生的推理 token 是成本比较的一部分，不得并入 output 后丢失。
- `raw` 保存用于审计与落盘的响应数据。非流式优先保存服务端 JSON；Responses 流保存服务端终结响应，标记 `format="provider-response"`；另外两种流保存统一结果摘要，标记 `format="litellm-normalized"`。后者不是原始 HTTP 响应，也不保留全部增量。旧磁带的 raw 仍作为不透明数据读取，replay 不依赖新旧 raw 的内部形状。
- 报告中的 `usage_missing` 按整个 Session 判断：任一轮缺少服务端用量，即标记整个 cell 的用量不完整。
- **空 `text` 永不静默接受**：端点未产出任何文本不是成功——适配器必须抛 `incomplete`（见「错误」），不得返回 `Completion(text="")`。

## LiteLLM 接入方案

当前实现采用 **LiteLLM Python SDK 1.106.0**，由 `src/llm/litellm_client.py` 封装；旧自建 HTTP／SSE 适配器已移除。依赖版本固定在 pyproject.toml 和锁文件中。

采用 [LiteLLM Python SDK](https://docs.litellm.ai/docs/python_sdk) 作为进程内依赖，不部署 LiteLLM Proxy。上层仍通过本项目的 `build_client` 和 `LLMClient.complete` 调用模型，不直接依赖 LiteLLM 类型。

```text
调用方：ModelConfig + list[Message]
    -> 项目 llm 封装：校验配置、解析凭证、选择调用入口
    -> LiteLLM：协议转换、HTTP 请求、响应及流式读取
    -> 项目 llm 封装：结果与错误转换
    -> Completion 或 LLMError(Failure)
```

### 职责分工

| 部分 | 责任 |
|---|---|
| 项目配置 | 保留 TOML、ModelConfig、未知字段检查、key_env 解析，以及项目约定的参数支持范围 |
| 项目公开接口 | 保留 Message、Completion、Usage、Failure、LLMClient 与 build_client，隔离第三方库类型 |
| LiteLLM | 复用协议请求与响应转换、HTTP 连接、流式读取和请求超时；关闭库及底层 SDK 的自动重试 |
| 项目结果处理 | 提取最终回答和服务端 usage，将库异常转换为项目错误类别，接入 on_delta 与运行日志 |
| 项目行为约束 | 保留空回答检查、输出上限要求、用量来源与流式完成判定；使用 Tenacity 对包含流式消费的完整尝试执行唯一重试预算 |

封装只补齐项目契约与所选库版本之间的差异，不维护另一套 HTTP／SSE 解码器。后续换库主要替换该实现和 build_client 的构造入口，上层输入输出类型保持独立。

该版本的 Responses 导入需要 `mcp` 包，因此安装 `litellm[mcp]`；这是 SDK 的依赖要求，不代表项目新增了 MCP 服务或工具协议。

### 配置与行为兼容

- 保留现有三个 `protocol` 配置值、模型名称和服务地址。LiteLLM 所需的 provider 前缀与参数名在封装内转换，不要求用户重写模型 TOML。
- 服务地址按原配置的含义转换，核对 `/v1`、`/responses`、`/chat/completions`、`/messages` 的实际请求路径，避免重复添加或遗漏路径。
- 保留未配置参数与明确设置参数的区别。项目要求报错的配置在请求前拒绝，不能依赖库自动补默认值或丢弃参数；例如 anthropic 未设置 output_length 仍须报 ConfigError。
- 当前 anthropic 的 reasoning_effort／extra_body 限制继续有效；库支持更多参数不自动扩大项目接口。extra_body 中的核心字段被过滤，即使相应配置未设置，也不能借此覆盖模型、消息或生成参数。
- 一次调用只有一个重试预算：LiteLLM 与底层 SDK 的重试均设为 0，Tenacity 最多执行 `max_transport_retries + 1` 次完整尝试。预算覆盖流式消费阶段；只重试打开 HTTP 请求不能处理收到部分文本后断连。错误映射按上层的记录与处理需求提供，不要求逐条复制旧实现。
- token 计数仍只取自服务端；缺少 usage 时保留 None，不使用库的本地估算补齐。核对推理 token、缓存 token 与各协议的合计口径。
- 不启用自动换模型、响应缓存、历史裁剪或消息内容改写；接入 SDK 不改变实验所选模型、对话内容及 replay 职责。
- 流式中途断连不能作为成功返回；没有有效结束信息或长期没有文本输出时显式失败。观察回调可能收到失败尝试的片段，因此最终回答仍以 Completion 为准。

### 固定版本的兼容处理

- LiteLLM 会为缺失的 usage 补零或估算。本项目从非流式调用钩子、SDK 已解码的 Responses 终结事件和 Anthropic 数据块保留服务端计数；Chat 流读取保留的服务端 chunk，不采用 SDK 最终估算。
- Anthropic 非流式响应缺少 usage 时，该版本的转换会异常。仅在已捕获合法 message 和非空文本、且服务端确实未提供 usage 时恢复回答，usage 保持 None。
- 对未知 Responses 模型，明确注册其原生流式能力，避免库根据模型目录改成模拟流式；不改配置中的模型名或选择其他模型。
- 流式观察仅消费 SDK 解码后的事件。Anthropic 流单独持有 HTTP transport 的生命周期，以便超时退出时关闭连接。

这些适配点集中在封装内部，升级 SDK 时需要重新运行三协议离线契约测试。迁移清单见[设计清理计划](../../plan/design-cleanup.md#litellm-客户端迁移)。

## 协议适配器

三个协议共用 `LLMClient`。协议转换交给 LiteLLM，项目封装负责选择入口及转换统一结果。

| 项目 protocol | LiteLLM 调用入口 | 路由方式 |
|---|---|---|
| `openai-response` | `litellm.responses` | 使用 OpenAI Responses 路径，传入模型、服务地址和 key |
| `anthropic` | `litellm.completion` | 使用 anthropic provider，由库转换为 Messages 请求 |
| `openai-completion` | `litellm.completion` | 使用 openai provider，调用兼容 Chat Completions 的服务 |

三种入口均通过实际 SDK 加 mock HTTP 的离线验证。参考 [Responses](https://docs.litellm.ai/docs/response_api)、[Anthropic](https://docs.litellm.ai/docs/providers/anthropic) 与 [OpenAI 兼容服务](https://docs.litellm.ai/docs/providers/openai_compatible)；离线验证不代表所有第三方端点都已实测。

| protocol | 请求地址 | system 处理 | reasoning 映射 |
|---|---|---|---|
| `openai-response` | `POST {base_url}/responses` | 顶层 `instructions` 字段 | `reasoning.effort` |
| `anthropic` | `POST {base_url}/v1/messages` | 顶层 `system` 字段 | v1 不下发（配置 `reasoning_effort` ⇒ `ConfigError`，不静默忽略） |
| `openai-completion` | `POST {base_url}/chat/completions` | `messages` 首条 `role=system` | `reasoning_effort` |

规则：

- 配置选型建议：优先选择 `openai-response` / `anthropic`，`openai-completion` 作为兼容选择。这不是 build_client 的运行限制，调用仍按显式配置分派。
- `anthropic` 协议必须明确设置 `output_length`（作为 `max_tokens` 发送，该协议强制）；其余协议下，未配置 `output_length` 时不发送该参数。
- 某协议不支持配置中出现的采样键 ⇒ `ConfigError`，**不静默忽略**。
- 已支持协议内换模型通过 TOML 配置完成。未来新增协议时先复用 LiteLLM 的支持，再补充项目配置与结果映射；LLMClient 与上层保持独立，本轮不新增协议。

## 错误

本节记录失败信息的对外承载方式。替换重点是调用方能识别失败并记录现场；内部分类与处理步骤可随 SDK 调整。

### 三通道

失败按「谁能修」分流。错误分类归 llm 模块：接收 LiteLLM 的异常和响应状态，再转换为本项目的 Failure；loop / experiment 只记录，不重新解释各服务商的错误。

| 通道 | 处理者 | 内容 |
|---|---|---|
| 对话通道 | 模型修 | parse 失败、工具领域错误——不进本层，见 [09](09-tools.md) |
| 重试通道 | client 修 | 传输级失败，由项目封装中的 Tenacity 执行唯一预算 |
| 失败通道 | 人修 | 不可重试或重试耗尽——抛 `LLMError`，携带结构化 `Failure` |

### `Failure`

```python
Failure = { stage: "llm",                  # 失败阶段（09 另定义 tool / extract）
            kind: str,                     # 见下表
            message: str,                  # 人读描述，不含密钥
            http_status: int | None,
            attempts: int,                 # 含重试的总尝试次数
            elapsed_s: float | None,       # 从发起到放弃的墙钟
            detail: dict }                 # 可用的错误码或 Retry-After 等现场；不保证各 SDK 异常字段相同
```

`LLMError.failure` 携带该结构。run 层把它**原样持久化**进 Session（见 [09](09-tools.md#session)）——错误细节在任何边界都不丢。

### kind 一览

| kind | 含义 | 通道 |
|---|---|---|
| `timeout` | 超时、网络断连或连续 300s 没有非空文本增量；包括从 SDK 包装异常中恢复出的传输错误 | 重试 → 失败 |
| `rate_limit` | HTTP 429；可识别的 Responses failed 状态中含 rate_limit／burst 的错误码 | 重试 → 失败 |
| `server` | HTTP 5xx；可识别的 Responses failed 状态中含 server 的错误码 | 重试 → 失败 |
| `auth` | HTTP 401 / 403 | 失败（不重试） |
| `rejected` | 其余 HTTP 非 2xx（400 / 404 / 409 / 422 …），`http_status` 必录 | 失败（不重试） |
| `protocol_mismatch` | SDK 无法解释响应结构，或没有更具体分类的协议错误 | 失败（不重试） |
| `incomplete` | 没有最终回答文本，或 SDK 正常返回后缺少有效完成信息 | 失败（不重试） |

- `incomplete` 单列的理由：它常是「模型把输出预算烧在 reasoning 上」或端点抽风——同参数重试是否值得**由实测决定，不猜**；单列后报告里可单独统计。
- SDK 可将流缺少终结事件报告为传输中断，此时归 timeout；不要求不同协议的底层异常完全相同。
- 当前退避规则：基础等待为 1s、2s、4s……，基础值封顶 60s；Retry-After 为可解析的秒数时，取两者较大值。记录实际尝试次数与包含等待的总耗时。
- **语义失败不是本层的事**：输出不合方言、工具报错等由 loop 作为对话反馈处理（见 [09](09-tools.md)），client 不知情。

### 可观测性

- **运行日志**：experiment CLI 将 llm／agent logger 写入 `<out>/logs/run.log`。llm 记录重试次数、类别及等待秒数；agent.loop 记录每轮调用与批量进度。模型配置由运行记录关联；不承诺旧适配器专有的 TTFT 或事件分布日志。
- **停滞保护**：HTTP 读取超时使用 timeout 与 300s 中较小值；另用有界队列观察 SDK 事件，连续 300s 没有非空回答或推理增量即退出。心跳不会刷新文本计时；生产线程异常必须传回调用线程，不能当作正常 EOF。
- 成功流的 raw 摘要包含 SDK 事件数。失败记录保留可用现场，API key 从 Failure 文本和 detail 中去除。
- 进度条的 out tok 是**全局跨 cell 累计**（轮末端点 usage 覆盖式写入），不代表单个 cell 的输出长度。

## 当前实现与迁移状态

- 2026-10-19 已迁移：配置与项目公开类型保持独立，三协议均通过实际 LiteLLM 的离线请求／流式契约测试，旧 adapters 与其失效测试已删除。
- 非流式 failed 状态即使包含部分文本也不能成功；部分输出后读取异常显式失败并按预算重试，两项已知缺陷已有回归。
- DeepSeek 小规模真实流式调用已返回 OK，服务端用量为输入 13、输出 1 token，关闭重试，输出上限 64。其他两种协议本轮只做离线验证，未运行实验矩阵。
- 完整验证、费用约束与保留的后续候选见[执行记录](../../plan/known-fixes-execution.md)。

## 验收

```text
实际 SDK 在 mock HTTP 下，对三协议生成正确的 URL、消息与参数
配置含未知键、或协议不支持出现的采样键 ⇒ ConfigError，不发请求
key_env 未设置 ⇒ CredentialError，不发请求
429/5xx/断连 ⇒ 重试通道耗尽后 LLMError(kind 对应, attempts>1)；4xx/auth ⇒ 立即失败 attempts==1
空文本响应 / 无 output 的流 ⇒ incomplete 或 protocol_mismatch，无 Completion(text="") 路径
全部 token 计数来自端点 usage 字段；代码中无本地估算路径
```

离线测试同时覆盖原配置载入、重试预算不叠加、三协议在流式和非流式下缺少 usage 不补估算，以及报告／Session／resume／replay。SDK 升级后需重跑这些验收；单个真实端点冒烟不替代跨协议契约测试。

## 边界

- 不定义工具、方言、终止条件（[09](09-tools.md)）；不定义执行矩阵与落盘（[11](11-experiment.md)）。
- 不缓存响应——replay 是 [11](11-experiment.md) 的磁带机制，不是 client 缓存。
- 流式只作观察通道（`on_delta`），不改变 `Completion` 语义与落盘内容。
- 多模态、API 级 function calling 不在本版（工具调用走文本方言，见 09）。
