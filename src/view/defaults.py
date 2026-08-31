"""view 的默认组件：id 策略 ``blockkey-as-is`` 与标注形式 ``xml-ish``。

对应 Docs/Design/07-agent-api.md「默认组件」节。两个默认实现相互独立，
由 Presenter 组合使用；都可按对应接口替换。
"""

from __future__ import annotations

from ir import Block

from view.types import AgentBlockId

__all__ = ["blockkey_as_is", "xml_ish"]


def blockkey_as_is(block: Block, index: int) -> AgentBlockId:
    """默认 id 策略 ``blockkey-as-is``：AgentBlockId = BlockKey。"""
    return block.key


def xml_ish(agent_id: AgentBlockId, content: str) -> str:
    """默认标注形式 ``xml-ish``（故意非良构，见 07-agent-api.md）::

        <x id="b3"\\>
        块内容原文，原样不转义
        </x>

    开标签 ``<x id="KEY"\\>``（``\\>`` 是字面反斜杠 + 大于号，在合法 XML
    中非法，使标注永远不会与文档自带的 XML 内容混淆），闭标签 ``</x>``。
    内容不做任何转义。开标签后、闭标签前各一个换行，闭标签后再跟一个换行，
    因此全量 payload 直接按序拼接各块标注即得。
    """
    return f'<x id="{agent_id}"\\>\n{content}\n</x>\n'
