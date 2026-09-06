根据上次实验设计的问题，重新设计的实验

## 实验1：探究输出阶段完整遍历注意力窗口与聚焦发现的错误的差异

上下文管理：

- system: BLOCR 提示词
  - find_replace 在最后追加 tool prompt
- first_user_message: 修复对象，均为原文

### Coding Plan（简要）

## 实验2：探究锚对结果的影响 + 按锚点聚焦的影响

上下文管理：

- system: BLOCR 提示词
  - find_replace 在最后追加 tool prompt
  - find_replace_blocked 再追加按块思考，再自由思考（注意力控制提示词）
  - patch_find_replace 在最后追加 tool prompt，除了规定如何输出，还要求先按块思考，再自由思考
- first_user_message: 打有行号锚的原文，修复的结果也是带有行号锚的。

### Coding Plan（简要）

## 实验3：探究不同锚对结果的影响

上下文管理：

- system: BLOCR 提示词
  - find_replace 在最后追加 tool prompt
  - patch_find_replace 在最后追加 tool prompt，除了规定如何输出，还要求先按块思考，再自由思考
- first_user_message: pending

## appendix

BLOCR提示词

```
```

find_replace tool prompt:

```
```

patch_find_replace tool prompt:

```
```

注意力控制提示词:

```
```
