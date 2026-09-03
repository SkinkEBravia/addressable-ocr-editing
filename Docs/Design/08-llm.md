# LLM 客户端

> 无前置依赖；被 [09-tools.md](09-tools.md) 的 loop 驱动。

## 范围

```text
list[Message] -> Completion        # 唯一的调用形态
```

`llm` 模块承担 LLM 访问的全部责任：协议适配、凭证解析、采样参数映射、错误分类与传输层重试。不感知工具、方言、数据集；**不持有对话状态**——历史由调用方持有，client 无状态。

## 定义

### `ModelConfig`

数据接口。一个可用模型的完整描述；TOML 一文件一模型，默认放 `configs/models/`，文件名即标签。

```toml
# configs/models/deepseek.toml
protocol        = "openai-completion"   # openai-completion | openai-response | anthropic
base_url        = "https://api.deepseek.com"
model           = "deepseek-chat"
key_env         = "DEEPSEEK_API_KEY"    # 环境变量名，间接引用
# 以下全部可选；缺席 = 不下发该参数，用端点默认
temperature     = 0.2
reasoning_effort = "low"                # low | medium | high
context_window  = 65536                 # 上下文窗口（信息性，暂不使用）
output_length   = 8192                  # 输出长度上限；显式值下发为 max_output_tokens / max_tokens
max_transport_retries = 3               # 重试通道上限
timeout         = 600.0                 # 单次请求墙钟上限
```

规则：

- **未知键直接报错**（防拼写漂移）。
- **采样参数全部允许留空**：缺席时不下发该参数——许多模型在端点默认状态下性能最好。「缺席」与「显式值」在解析后的配置中可区分。
- `context_window` 是声明性信息：供将来的历史管理与预算核算使用，不改变请求行为。
- `output_length` 是采样键：显式值下发为 `max_output_tokens`（openai-response）/ `max_tokens`（openai-completion / anthropic）。**必须下发**——端点默认上限可能远低于模型能力（volc 实测默认 ≈32k，模型上限 384k），不下发则长输出任务被默认预算截断成 `incomplete`。anthropic 协议下为强制字段。
- 采样参数属于模型配置：同一实验内各工具配置共用同一模型配置（公平性，见 [11](11-experiment.md#公平性)）。

### 凭证

- key 只从环境变量读取。装配层在任何解析之前，先把项目根 `.env`（若存在）加载进进程环境——项目专属凭证不进系统环境。
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
- `raw` 为端点原始响应，供审计与落盘。
- **空 `text` 永不静默接受**：端点未产出任何文本不是成功——适配器必须抛 `incomplete`（见「错误」），不得返回 `Completion(text="")`。

## 接口

```python
class LLMClient(Protocol):
    def complete(
        self,
        messages: list[Message],
        *,
        on_delta: Callable[[str], None] | None = None,   # 可选观察通道
    ) -> Completion: ...

def build_client(config: ModelConfig) -> LLMClient
```

- `on_delta` 非空 ⇒ 适配器以流式请求，逐增量回调（content 与 reasoning 增量都进回调）；回调**只作观察**，`Completion` 语义与非流式完全一致，usage 仍取自端点（流式经端点的 usage 事件/字段获得）。
- **是否流式由调用方显式决定**（09 的 loop 经运行参数控制），client 不自行嗅探调用方能力。
- `on_delta` 为空 ⇒ 普通非流式请求。

## 协议适配器

三个适配器共用 `LLMClient`，只做线格式互转与 usage 提取，不改写内容。

| protocol | 线格式 | system 处理 | reasoning 映射 |
|---|---|---|---|
| `openai-response` | `POST {base_url}/responses` | 顶层 `instructions` 字段 | `reasoning.effort` |
| `anthropic` | `POST {base_url}/v1/messages` | 顶层 `system` 字段 | v1 不下发（配置 `reasoning_effort` ⇒ `ConfigError`，不静默忽略） |
| `openai-completion` | `POST {base_url}/chat/completions` | `messages` 首条 `role=system` | `reasoning_effort` |

规则：

- **接入优先级：`openai-response` / `anthropic` 优先，`openai-completion` 是次级兼容选择**。
- `anthropic` 协议必须显式 `output_length`（作为 `max_tokens` 下发，该协议强制）；其余协议下 `output_length` 缺席 = 不下发。
- 某协议不支持配置中出现的采样键 ⇒ `ConfigError`，**不静默忽略**。
- 换模型 = 换 TOML，不动代码；新协议 = 新增一个适配器，`LLMClient` 与上层不变。

## 错误

### 三通道

失败按「谁能修」分流，**分类只发生在适配器**（它持有协议知识）；loop / experiment 只记录，不分类。

| 通道 | 处理者 | 内容 |
|---|---|---|
| 对话通道 | 模型修 | parse 失败、工具领域错误——不进本层，见 [09](09-tools.md) |
| 重试通道 | client 修 | 传输级失败，适配器内指数退避，`max_transport_retries` 封顶 |
| 失败通道 | 人修 | 不可重试或重试耗尽——抛 `LLMError`，携带结构化 `Failure` |

### `Failure`

```python
Failure = { stage: "llm",                  # 失败阶段（09 另定义 tool / extract）
            kind: str,                     # 见下表
            message: str,                  # 人读描述，不含密钥
            http_status: int | None,
            attempts: int,                 # 含重试的总尝试次数
            elapsed_s: float | None,       # 从发起到放弃的墙钟
            detail: dict }                 # 现场：SSE 事件计数、终结事件类型、body 摘录（截断）等
```

`LLMError.failure` 携带该结构。run 层把它**原样持久化**进 Session（见 [09](09-tools.md#failure)）——错误细节在任何边界都不丢。

### kind 一览

| kind | 含义 | 通道 |
|---|---|---|
| `timeout` | 超时 / 网络断连（含对端无响应断开），重试耗尽后 | 重试 → 失败 |
| `rate_limit` | HTTP 429，尊重 `Retry-After` | 重试 → 失败 |
| `server` | HTTP 5xx | 重试 → 失败 |
| `auth` | HTTP 401 / 403 | 失败（不重试） |
| `rejected` | 其余 HTTP 非 2xx（400 / 404 / 409 / 422 …），`http_status` 必录 | 失败（不重试） |
| `protocol_mismatch` | 2xx 但响应体 / 事件形状不符协议（非 JSON、缺字段） | 失败（不重试） |
| `incomplete` | 流式收尾无任何 output 文本（`response.incomplete`、空流、`response.failed` 无映射错误码） | 失败（不重试） |

- `incomplete` 单列的理由：它常是「模型把输出预算烧在 reasoning 上」或端点抽风——同参数重试是否值得**由实测决定，不猜**；单列后报告里可单独统计。
- 重试通道内：指数退避（1s, 2s, 4s, … 封顶 60s），端点给了 `Retry-After` 则从其值。
- **语义失败不是本层的事**：输出不合方言、工具报错等由 loop 作为对话反馈处理（见 [09](09-tools.md)），client 不知情。

## 验收

```text
三适配器对同一 (messages, ModelConfig) 产出各自正确线格式（录制响应回放的 golden 测试）
配置含未知键、或协议不支持出现的采样键 ⇒ ConfigError，不发请求
key_env 未设置 ⇒ CredentialError，不发请求
429/5xx/断连 ⇒ 重试通道耗尽后 LLMError(kind 对应, attempts>1)；4xx/auth ⇒ 立即失败 attempts==1
空文本响应 / 无 output 的流 ⇒ incomplete 或 protocol_mismatch，无 Completion(text="") 路径
全部 token 计数来自端点 usage 字段；代码中无本地估算路径
```

## 边界

- 不定义工具、方言、终止条件（[09](09-tools.md)）；不定义执行矩阵与落盘（[11](11-experiment.md)）。
- 不缓存响应——replay 是 [11](11-experiment.md) 的磁带机制，不是 client 缓存。
- 流式只作观察通道（`on_delta`），不改变 `Completion` 语义与落盘内容。
- 多模态、API 级 function calling 不在本版（工具调用走文本方言，见 09）。
