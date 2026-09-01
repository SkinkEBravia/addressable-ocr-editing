# 外部接口：Agent 操作面与 CLI

> 前置概念：[View 与 Agent 操作面](../Concepts/04-view.md)；报错能力：[OpError](04-ir-ops.md#operror)；视图：[06-view.md](06-view.md)

## 范围

两个入口，同一条链路：

```text
patch 文本 --解析--> surface ops --降解--> core ops --apply--> 新快照 --渲染--> 受影响块
```

Agent 接口是库内调用，CLI 是同一操作面的进程化封装——**CLI 的主要用户也是 Agent**，因此两者共享方言、错误格式与会话目录。

## SurfaceOp 标准集

surface 层固定提供七个操作：四个核心 op 的直译 + 三个包装。

| SurfaceOp | 语义 | 降解 |
|---|---|---|
| `set_content(id, text)` | 整体替换内容 | `SetContent(key, text)` |
| `set_attrs(id, obj)` | 整体替换 attrs | `SetAttrs(key, obj)` |
| `append(anchor, text, attrs?)` | 插入到 anchor 之后 | `Append(draft, at: key)` |
| `remove(id)` | 移除块 | `Remove(key)` |
| `move(id, anchor)` | 移动到 anchor 之后 | `Remove` + `Append`，**身份变更新 key** |
| `merge(a, b)` | b 并入 a 末尾，b 移除 | `SetContent` + `Remove` |
| `replace(id, old, new)` | 块内片段替换，`old` 的全部出现处都换成 `new` | `SetContent(key, content.replace(old, new))` |

`replace` 的规则：

- `old` 必须在块的批次内累计内容（含同批次前序操作的结果，见「规则」）中至少出现一次，否则降解失败（`PATTERN_NOT_FOUND`），不进 `apply`。
- 多处出现全部替换；需要只改一处时，调用方用更长的上下文使 `old` 唯一。
- 定位由块负责（行级），变更粒度到片段——稀疏错误下避免整块重写。

规则：

- `id` / `anchor` 均为 `AgentBlockId`；`anchor` 可取头部保留值。
- 同一 patch 内的所有 id 以 **patch 之前的 View** 为准；patch 内不得引用本次新建的块（其 id 在结果中返回，供下一次 patch 使用）。
- **内容操作链式叠加**：同一 patch 内对同一块的内容操作按文本顺序生效——`replace` / `merge` 看到同批次前面 `set_content` / `replace` 的结果，`move` 带走的也是最新内容；`set_content` 是绝对重置。

## 定义

### patch 方言

方言 = 文本格式 + 解析器。可替换点：换方言只换解析器。

```python
def parse(patch_text: str) -> tuple[SurfaceOp, ...]
```

每条 `SurfaceOp` 记录其在 patch 文本中的位置（行号区间），供报错定位。

### 降解

```python
def degrade(surface_ops: tuple[SurfaceOp, ...], ref_map: ReferenceMap, snapshot: DocumentSnapshot) -> tuple[CoreOpEntry, ...]
```

- `AgentBlockId` 经 `ReferenceMap` 换回 `BlockKey`。
- 包装语义按上表展开为核心 op 序列。
- `snapshot` 为 patch 前快照：move / merge / replace 的展开需要读取块内容，并按「内容操作链式叠加」规则读取批次内累计内容。
- `CoreOpEntry = (Op, origin)`：`origin` 指回产生它的 `SurfaceOp`（序号 + 文本位置）。**溯源信息是报错包装的前提**。

### 错误回传

失败信息分三层逐层包装，最终送达 Agent 的是 surface 层定位：

```text
OpError(index, op, reason)                     # IR 层：批次内哪条 core op、为什么
  └─ origin ──> SurfaceError                   # 操作面层：哪条 surface op、它被展开成了什么
       └─ 方言格式化 ──> 报错输出               # 文本层：patch 中的行号 + 人读描述
```

| 层 | 类型 | 字段 |
|---|---|---|
| IR | `OpError` | 见 04 |
| 操作面 | `SurfaceError` | `stage`、`surface_index`、`position`（行号区间）、`expanded`（展开出的 core ops）、`cause: str \| None`、`message` |
| 输出 | 文本 / JSON | 由方言或 CLI 格式化 |

`cause` 是机器可判读的原因码：`apply` 失败时为 `OpError.reason`（`KEY_NOT_FOUND` 等）；降解失败时一般为 `None`，`replace` 的 `old` 未出现时为 `PATTERN_NOT_FOUND`。

行为规则：

- 降解阶段失败（未知 `AgentBlockId`、`replace` 的 `old` 未出现等）直接产出 `SurfaceError`，不进入 `apply`。
- `apply` 失败时，用 `OpError.index` 查 `origin` 回溯到 `SurfaceOp`。
- 预检免费：`apply` 纯函数，先试跑拿错误，成功才提交 store。

### `PatchResult`

数据接口。一次 patch 的回执。

| 字段 | 类型 | 说明 |
|---|---|---|
| `snapshot_id` | `SnapshotId` | 新快照 |
| `affected` | `list[AffectedBlock]` | 受影响的块，按文档序；同一块被多条 op 命中只出现一次（位置取首次出现，`status` 取最后一次） |

`AffectedBlock`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `key` | `BlockKey` | 块身份 |
| `agent_id` | `AgentBlockId` | 新 View 下的 id |
| `status` | `str` | `appended` / `updated` / `moved` / `merged` / `removed` |
| `annotated` | `str \| None` | 用同一 `(strategy, annotator)` 渲染的带标注内容；`removed` 时为 `None` |

目的：改完即可核对，不必重新拉全量 View。渲染风格与 View 一致，Agent 认知成本低。

## 默认组件

第一版交付的默认栈；每个组件都可按对应接口替换。

| 组件 | 默认实现 | 定义位置 |
|---|---|---|
| partition | `partition_chars` | [02](02-partition.md#参考实现按字数切分) |
| id 策略 | `blockkey-as-is`：`AgentBlockId = BlockKey` | 本节 |
| 标注形式 | `xml-ish`（下文） | 本节 |
| patch 方言 | `fn`（下文） | 本节 |

### 标注形式 `xml-ish`

```text
<x id="b3"\>
块内容原文，原样不转义
</x>
```

- 开标签 `<x id="KEY"\>`，闭标签 `</x>`，逐块包裹。
- `\>` 在合法 XML 中非法——**故意非良构**，使标注永远不会与文档自带的 XML 内容混淆。
- 内容不做任何转义；标注与内容的边界由标签模式唯一确定。

### 方言 `fn`

一行一个函数调用：

```text
set_content(b3, "替换后的全文")
set_attrs(b3, {"start": 120})
append(b2, "新块内容")
append(HEAD, "文首新块", {"kind": "intro"})
remove(b4)
move(b1, b5)
merge(b1, b2)
replace(b3, "teh", "the")
```

语法规则：

- 全部位置参数；id 为裸标识符（`HEAD` 表示头部锚点）。
- 字符串与 attrs 对象使用 JSON 语法（转义、多行由 JSON 字符串承担）。
- 空行与 `#` 开头的行忽略。
- 按文本顺序依次降解、一次性 `apply`。

## CLI 对方言的限制

CLI 是方言的真实使用环境，方言设计服从以下约束：

1. **patch 只经 stdin 或文件传入，不经 argv**——方言文本不受 shell 转义限制，可自由使用任意字符与多行结构。
2. **输出双格式**：默认人读文本，`-f json` 输出机读 JSON；`PatchResult` 与 `SurfaceError` 都直接序列化，Agent 凭 JSON 自行修复重试。
3. **退出码**：`0` 成功；`1` 解析失败，`2` 降解失败，`3` apply 失败，`4` I/O 失败。
4. **进程模型**：单发进程，启动时读 `current`，提交时写 store（见 05）。并发写不在 v1 范围，调用方串行执行。

## 接口

```python
# Agent 接口（库内）
def run_patch(store, patch_text: str, strategy: AgentIdStrategy, annotator: Annotator) -> PatchResult
# 失败抛 ParseError / SurfaceError（均带 to_dict()；CLI 凭异常类型映射退出码）
```

```text
# CLI（会话目录共享状态）
doc ingest <file> --session <dir> [--partition chars]
doc view --session <dir>                            # 打印 AgentView payload
doc patch --session <dir> [-f json] < patch.txt     # 预检 + apply + save + 返回受影响块
doc write --session <dir> [-o <path>]               # reconstruct + sourceio.write
doc rollback <SnapshotId> --session <dir>           # set_current
```

各命令即链路片段的装配：`ingest` = read + partition + birth + save；`patch` = load + parse + degrade + 试跑 + save + 渲染受影响块；`write` = load + reconstruct + write。

## 验收

```text
patch 失败 ⇒ store 不变，退出码非 0，输出含 surface 层行号与原因码
patch 成功 ⇒ 返回新 SnapshotId 与全部受影响块的标注渲染
ingest → 无 patch → write 的产物与原文件逐字节相同
```

## 边界

- 方言、id 策略、标注形式各自可替换，互不影响；CLI 与 Agent 接口只认 `SurfaceOp`，不感知方言语法。
- View 的生成归 `06-view.md`；CLI 的 `view` 命令只是其调用方。
- 并发控制、锁、网络服务不在 v1。
