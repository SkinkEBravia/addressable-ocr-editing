# 中间表示 · 状态迁移（Ops）

> 前置概念：[文档层](../Concepts/03-document-layer.md)；数据结构：[03-ir-data.md](03-ir-data.md)

## 范围

定义核心操作集的语义、`apply` 的执行规则与 RollBack。
不含存储与快照留存机制（见 `05-ir-io.md`），不含 surface 语义（拆块、并块等，归 Agent 面降解）。

## 定义

### `Op`

```text
Op = Append(draft: BlockDraft, at: BlockKey | HEAD)
   | Remove(key: BlockKey)
   | SetContent(key: BlockKey, content: str)
   | SetAttrs(key: BlockKey, attrs: Attrs)
```

封闭集合，无其他迁移方式。

### 语义

| Op | 前置条件 | 效果 |
|---|---|---|
| `Append` | 锚点存在或为 `HEAD` | 分配器取新 key（`key_cursor + 1`），新块插到锚点之后；锚点为末块即尾部追加。同一锚点的连续插入为**栈序**：后插入的更靠近锚点 |
| `Remove` | `key` 存在且 ≠ `HEAD` | 移除该块；其 key 永久作废，不复用 |
| `SetContent` | `key` 存在 | 整体替换 `content` |
| `SetAttrs` | `key` 存在 | 整体替换 `attrs`（合并归调用方负责） |

## 接口

```python
def apply(snapshot: DocumentSnapshot, ops: tuple[Op, ...]) -> DocumentSnapshot
```

行为规则：

- 批次内按序应用，**原子**：任一 op 失败抛出 `OpError`，不产生新快照，原快照不变。
- `ops` 为空时返回原快照，不产出新 `SnapshotId`。
- 成功时产出一个新快照：新 `SnapshotId`、推进后的 `key_cursor`、应用后的 `blocks` 与 `doc_attrs`。
- 新 `SnapshotId` = 对快照（不含 `id` 字段）的规范化 JSON 取内容哈希，加 `s-` 前缀。分叉安全，相同内容得到相同 id。

### `OpError`

数据接口。`apply` 失败的全部信息，供上层定位与包装。

| 字段 | 类型 | 说明 |
|---|---|---|
| `index` | `int` | 失败 op 在批次内的序号 |
| `op` | `Op` | 失败的那条 op |
| `reason` | `str` | `KEY_NOT_FOUND` / `BAD_ANCHOR` 等机器可判读的原因码 |
| `key` | `BlockKey \| None` | 涉及的 key（如有） |

`apply` 是纯函数：预检 = 对同一快照试跑，成功则丢弃结果，失败即得 `OpError`，无任何副作用。

### RollBack

```python
def rollback(target: SnapshotId) -> None
```

- **不是 Op**，不产生新快照。语义仅为：把当前指针移动到 store 中已有的某个快照。
- 目标之后的快照不删除（append-only）；回滚后再编辑即分叉，新快照从目标快照继续取号。

## surface 语义的降解

核心集之外的操作不进入文档层，由调用方展开为核心 op 序列后一次性 `apply`：

```text
move(k, at)      = Remove(k) + Append(draft_of(k), at)   # 身份不保留，新块取新 key
merge(a, b)      = SetContent(a, a.content + b.content) + Remove(b)
split(k, i)      = SetContent(k, content[:i]) + Append(draft(content[i:]), at: k)
replace(k, o, n) = SetContent(k, content.replace(o, n))  # o 未出现：表面层失败，不进 apply
```

move 不保身份是核心集的直接推论；需要保身份的 move 属于概念层改动，不在本模块解决。

## 验收

```text
apply(s, ()) == s
ops 中任一失败 ⇒ 无新快照，s 不变
rollback(t) 后 current == t，store 中历史快照全部保留
```

## 边界

- 不产出、不存储逆操作；撤销能力由快照留存与 RollBack 承担。
- 不持有历史与指针——两者归 store / 装配层（`05-ir-io.md`）。
- 不感知 View、AgentBlockId 与 patch 方言。
