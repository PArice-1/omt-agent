"""经真实统一模型、Agent、Conversation 验证工具循环、v3 事件和检查点兼容。"""

import asyncio
import json
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import HttpUrl, SecretStr

from omt.agent.agent import Agent
from omt.ai.model import Model
from omt.core.conversation import Conversation
from omt.core.events import RunEvent
from omt.core.usage import UsageSnapshot, usage_from_messages
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler, HTTPHandler


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(("model", "effort"), [("deepseek-chat", "high"), ("deepseek-v4-flash", "max")])
def test_existing_conversation_interface_stream_tools_and_resume(asynchronous: bool, model: str, effort: str) -> None:
    """消费分片工具调用并恢复历史；Flash 的 max 在工具轮和恢复后都不能丢。"""
    requests: list[dict[str, Any]] = []
    received: list[RunEvent] = []
    executions: list[int] = []

    @tool
    def double(value: int) -> str:
        """将测试整数翻倍，记录副作用以检查工具仅执行一次。"""
        executions.append(value)
        return str(value * 2)

    def respond(request: httpx.Request) -> httpx.Response:
        """模拟 DeepSeek SSE，不替换 SDK 的参数映射、消息转换或工具绑定。"""
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.path == "/v1/chat/completions" and body["stream"] is True
        assert body["tools"][0]["function"]["name"] == "double"
        if model == "deepseek-v4-flash":
            assert body["model"] == model
            assert body["thinking"] == {"type": "enabled"} and body.get("reasoning_effort") == "max"
        assert body["stream_options"]["include_usage"] is True
        if len(requests) == 1:
            deltas = [
                {"role": "assistant", "reasoning_content": "先"},
                {"reasoning_content": "调用工具"},
                {"tool_calls": [{"index": 0, "id": "call-test", "type": "function",
                                 "function": {"name": "double", "arguments": '{"value":'}}]},
                {"tool_calls": [{"index": 0, "function": {"arguments": "4}"}}]},
            ]
            finish = "tool_calls"
        else:
            deltas = [{"role": "assistant", "reasoning_content": "检查结果"}, {"content": "结果"}, {"content": "是8"}]
            finish = "stop"
        frames: list[dict[str, object]] = [{"id": f"reply-{len(requests)}", "object": "chat.completion.chunk", "created": 1,
                   "model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
                  for delta in deltas]
        frames.append({"id": f"reply-{len(requests)}", "object": "chat.completion.chunk", "created": 1,
                       "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
        frames.append({"id": f"reply-{len(requests)}", "object": "chat.completion.chunk", "created": 1,
                       "model": model, "choices": [],
                       "usage": {"prompt_tokens": 100 * len(requests), "completion_tokens": 20,
                                 "total_tokens": 100 * len(requests) + 20}})
        sse = "".join(f"data: {json.dumps(frame, ensure_ascii=False)}\n\n" for frame in frames) + "data: [DONE]\n\n"
        return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})

    def make_conversation(handler: object) -> Conversation:
        client = Model("deepseek", model=model, base_url=HttpUrl("https://example.test/v1"),
                       api_key=SecretStr("fake-key"), reasoning_effort=effort, client=handler)
        return Conversation(Agent(client.model, tools=[double], checkpointer=InMemorySaver()),
                            {"configurable": {"thread_id": "litellm-compat"}},
                            skill_roots=[], event_handler=received.append)

    async def execute() -> Conversation:
        handler = AsyncHTTPHandler(transport=httpx.MockTransport(respond))
        try:
            conversation = make_conversation(handler)
            assert await asyncio.wait_for(conversation.arun("翻倍4"), 5) == "结果是8"
            restored = Conversation(conversation.agent, skill_roots=[])
            await restored.load_history("litellm-compat")
            assert len(restored.messages) == 4
            assert await asyncio.wait_for(restored.arun("再确认"), 5) == "结果是8"
            return restored
        finally:
            await handler.client.aclose()

    if asynchronous:
        final = asyncio.run(execute())
    else:
        with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
            conversation = make_conversation(HTTPHandler(client=transport))
            assert conversation.run("翻倍4") == "结果是8"
            final = Conversation(conversation.agent, skill_roots=[])
            asyncio.run(final.load_history("litellm-compat"))
            assert len(final.messages) == 4
            assert final.run("再确认") == "结果是8"
    assert executions == [4] and len(requests) == 3
    reports = [event.data for event in received if event.kind == "usage.updated"]
    assert all(isinstance(report, UsageSnapshot) for report in reports)
    assert [report.total_tokens for report in reports if isinstance(report, UsageSnapshot)] == [120, 340]
    summary = usage_from_messages(final.messages)
    assert summary.total_tokens == 660 and summary.context_tokens == 320 and summary.usage_complete
    assert [message.type for message in final.messages] == ["human", "ai", "tool", "ai", "human", "ai"]
    assert isinstance(final.messages[1], AIMessage) and final.messages[1].tool_calls[0]["args"] == {"value": 4}
    assert isinstance(final.messages[2], ToolMessage) and final.messages[2].tool_call_id == "call-test"
    assert final.messages[2].content == "8"
    assert requests[1]["messages"][-1] == {"role": "tool", "content": "8", "tool_call_id": "call-test"}
    assert requests[1]["messages"][-2]["reasoning_content"] == "先调用工具"
    assert len(requests[2]["messages"]) == 5
    assert "".join(event.text for event in received if event.kind == "assistant.delta") == "结果是8"
    assert "".join(event.text for event in received if event.kind == "assistant.reasoning.delta") == "先调用工具检查结果"
    assert [event.tool_call_id for event in received if event.kind == "tool.completed"] == ["call-test"]
