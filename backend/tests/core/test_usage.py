"""用公开会话执行和历史投影区分累计消耗、上下文占用及缺失用量。"""

import asyncio
from typing import Self, override

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from omt.agent.agent import Agent
from omt.core.conversation import Conversation
from omt.core.events import RunEvent
from omt.core.usage import UsageSnapshot, compact_tokens, format_usage, token_counts, usage_from_messages


class UsageModel(FakeMessagesListChatModel):
    """只返回测试创建的消息，不读配置、不请求网络。"""

    @override
    def bind_tools(self, tools: object, **kwargs: object) -> Self:
        return self


@pytest.mark.parametrize("asynchronous", [False, True])
def test_conversation_reports_tool_only_call_and_cumulative_multiturn_usage(asynchronous: bool) -> None:
    """纯工具请求也消耗 token；第二轮累计不重复计历史，占用只取最后请求。"""
    @tool
    def local_value() -> str:
        """返回内存测试值，无外部副作用。"""
        return "值"

    received: list[RunEvent] = []
    model = UsageModel(responses=[
        AIMessage(content="", tool_calls=[{"name": "local_value", "args": {}, "id": "tool-1"}],
                  usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}),
        AIMessage(content="完成", usage_metadata={"input_tokens": 200, "output_tokens": 30, "total_tokens": 230}),
        AIMessage(content="继续", usage_metadata={"input_tokens": 300, "output_tokens": 40, "total_tokens": 340}),
    ])
    conversation = Conversation(Agent(model, tools=[local_value]), skill_roots=[], event_handler=received.append)

    async def execute() -> None:
        assert await conversation.arun("运行工具") == "完成"
        assert await conversation.arun("继续") == "继续"

    if asynchronous:
        asyncio.run(execute())
    else:
        assert conversation.run("运行工具") == "完成"
        assert conversation.run("继续") == "继续"
    reports = [event.data for event in received if event.kind == "usage.updated"]
    assert [usage.total_tokens for usage in reports if isinstance(usage, UsageSnapshot)] == [120, 350, 690]
    snapshot = usage_from_messages(conversation.messages).with_window(1000)
    assert snapshot.input_tokens == 600 and snapshot.output_tokens == 90
    assert snapshot.total_tokens == 690 and snapshot.context_tokens == 340
    assert snapshot.context_used_percent == 34 and snapshot.context_remaining_tokens == 660
    assert snapshot.usage_complete


def test_history_usage_missing_latest_call_is_unknown_not_zero_or_stale() -> None:
    messages = [HumanMessage(content="问题"),
                AIMessage(content="已知", usage_metadata={"input_tokens": 80, "output_tokens": 20, "total_tokens": 100}),
                ToolMessage(content="不另行计费", tool_call_id="id"), AIMessage(content="旧模型未报告")]
    snapshot = usage_from_messages(messages).with_window(272000)
    assert snapshot.total_tokens == 100 and not snapshot.usage_complete
    assert snapshot.context_tokens is None and snapshot.context_used_percent is None
    assert snapshot.context_remaining_tokens is None
    assert format_usage(snapshot) == "≥100 token --%/272k"
    assert token_counts({"input_tokens": -1, "output_tokens": 0, "total_tokens": 0}) is None
    assert token_counts({"input_tokens": 0}) is None
    assert token_counts({"input_tokens": True, "output_tokens": 0, "total_tokens": 1}) is None


def test_initial_unknown_switch_and_overflow_windows_do_not_change_consumption() -> None:
    initial = UsageSnapshot().with_window(272000)
    assert format_usage(initial) == "0 token 0%/272k"
    assert initial.context_remaining_tokens == 272000
    assert format_usage(initial.with_window(None)) == "0 token --%/--"
    used = UsageSnapshot(total_tokens=1000, context_tokens=500).with_window(1000)
    switched = used.with_window(250)
    assert switched.total_tokens == 1000 and switched.context_used_percent == 200
    assert switched.context_remaining_tokens == 0


@pytest.mark.parametrize(("value", "expected"), [
    (0, "0"), (100, "100"), (999, "999"), (1000, "1k"), (12500, "12.5k"),
    (999999, "1m"), (1000000, "1m"), (1250000, "1.3m"), (1000000000, "1b"),
])
def test_compact_tokens_uses_decimal_units(value: int, expected: str) -> None:
    assert compact_tokens(value) == expected
