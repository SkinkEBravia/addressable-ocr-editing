# LLM 客户端与对话

> 前置：无（本模块不依赖 IR / View / surface）；被 [09-tools.md](09-tools.md) 的 loop 驱动。

## 范围

```text
list[Message] -> Completion        # 唯一的调用形态
```

`llm` 模块承担 LLM 访问的全部责任：协议适配、凭证解析、采样参数映射、传输层重试。
不感知工具、方言、数据集；**不持有对话状态**——历史由调用方持有，client 无状态。

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
output_length   = 8192                  # 输出长度上限（信息性，暂不使用）
```

规则：

- **未知键直接报错**（防拼写漂移）。
- **采样参数全部允许留空**：`temperature` / `reasoning_effort` 缺席时不下发该参数——许多模型在端点默认状态下性能最好，默认值是端点的事，不是配置的事。「缺席」与「显式值」在解析后的配置中可区分。
- `context_window` / `output_length` 是声明性信息：供将来的历史管理（09 的轮内截断）与预算核算使用，v1 不改变请求行为。
- 采样参数属于模型配置：同一实验内各工具配置共用同一模型配置（公平性，见 [11](11-experiment.md#公平性)）。

### 凭证

- key 只从环境变量读取。装配层在任何解析之前，先把项目根 `.env`（若存在）加载进进程环境——项目专属凭证不进系统环境。
- `.env` 与任何含 key 的文件必须 gitignore（已含 `.env`、`deep_seek.txt`）；配置、报告、对话录中只允许出现 `key_env` 的**名字**。
- `key_env` 未设置 ⇒ `CredentialError`，不发请求。

### `Message` / `Completion` / `Usage`

```python
Message = { role: "system" | "user" | "assistant", content: str }

Completion = { text: str, usage: Usage | None, raw: JsonValue }
Usage = { input_tokens: int, output_tokens: int, reasoning_tokens: int | None }
```

- token 计数一律取自端点 `usage` 字段，**不做本地估算**；端点不返回时 `usage = None`，报告记 `usage_missing`。
- `reasoning_tokens` 单列：思考强度产生的推理 token 是成本比较的一部分，不得并入 output 后丢失。
- `raw` 为端点原始响应，供审计与落盘。

## 接口

```python
class LLMClient(Protocol):
    def complete(self, messages: list[Message]) -> Completion: ...

def build_client(config: ModelConfig) -> LLMClient
```

## 协议适配器

三个适配器共用 `LLMClient`，只做线格式互转与 usage 提取，不改写内容。

| protocol | 线格式 | system 处理 | reasoning 映射 |
|---|---|---|---|
| `openai-completion` | `POST {base_url}/chat/completions` | `messages` 首条 `role=system` | `reasoning_effort` |
| `openai-response` | `POST {base_url}/responses` | 顶层 `instructions` 字段 | `reasoning.effort` |
| `anthropic` | `POST {base_url}/v1/messages` | 顶层 `system` 字段 | `thinking` 段 |

规则：

- 某协议不支持配置中出现的采样键 ⇒ `ConfigError`，**不静默忽略**（公平性要求参数要么生效、要么报错）。
- 换模型 = 换 TOML，不动代码；新协议 = 新增一个适配器，`LLMClient` 与上层不变。

## 错误与重试

`LLMError` 的 `kind`：`timeout` / `rate_limit` / `server` / `auth` / `bad_response`。

- 传输层重试（`timeout` / `rate_limit` / `server`）在 client 内完成：指数退避，尊重端点 `Retry-After`，上限 `max_transport_retries`（缺省 3）。
- `auth` / `bad_response` 不重试。
- **语义失败不是本层的事**：输出不合方言、工具报错等由 loop 作为对话反馈处理（见 [09](09-tools.md)），client 不知情。

## 对话

对话 = 调用方持有的 `list[Message]`；一轮产生一条记录：

```python
Turn = { index: int, completion: Completion }
```

- client 无状态 ⇒ 同一 `messages` 前缀可重放、可分叉；多轮对话只是逐轮追加消息后重复调用。
- 一次对话的 token 合计 = 各轮 `usage` 之和（含失败轮）。
- 对话录的落盘格式与 replay 归 [11](11-experiment.md#对话录)。

## 验收

```text
三适配器对同一 (messages, ModelConfig) 产出各自正确线格式（录制响应回放的 golden 测试）
配置含未知键、或协议不支持出现的采样键 ⇒ ConfigError，不发请求
key_env 未设置 ⇒ CredentialError，不发请求
全部 token 计数来自端点 usage 字段；代码中无本地估算路径
```

## 边界

- 不定义工具、方言、终止条件（[09](09-tools.md)）；不定义执行矩阵与落盘（[11](11-experiment.md)）。
- 不缓存响应——replay 是 11 的对话录机制，不是 client 缓存。
- 流式输出、多模态、API 级 function calling 不在 v1（工具调用走文本方言，见 09）。
