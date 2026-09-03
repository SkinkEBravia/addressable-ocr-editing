"""llm 的协议适配器：openai-response / anthropic / openai-completion。

对应 Docs/Design/08-llm.md「协议适配器」节。共用 _transport 的重试驱动
与状态分类；适配器只做线格式互转与 usage 提取。
"""
