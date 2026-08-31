# 概念：严格分区

> **定义 1（无损严格分区）**
>
> 设原始序列 $S$，长度 $\vert S \vert$。合法的切分计划为区间序列 $P = (\tau_1, \dots, \tau_n)$，其中 $\tau_i = [\tau_i.\mathrm{start}, \tau_i.\mathrm{end})$，满足：
>
> 1. **首尾封闭**：$\tau_1.\mathrm{start} = 0 \land \tau_n.\mathrm{end} = \vert S \vert$
> 2. **链式连续**：$\forall i \in [1, n-1],\; \tau_i.\mathrm{end} = \tau_{i+1}.\mathrm{start}$
> 3. **非空区间**：$\forall i \in [1, n],\; \tau_i.\mathrm{start} < \tau_i.\mathrm{end}$
>
> 空序列是唯一的例外：$\vert S \vert = 0$ 时合法的计划只有 $n = 0$ 一个，且 $\mathrm{concat}(\varnothing) = \varepsilon$。

切片（$\mathrm{materialize}$）与折回（$\mathrm{concat}$）满足恒等式：

$$
S = \mathrm{concat}(S[\tau_1], S[\tau_2], \dots, S[\tau_n])
$$

这个无损对任意序列成立：任何序列化的文件都能在切片与原序列之间无损转换。
