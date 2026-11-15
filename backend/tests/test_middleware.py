"""通过真实 Agent 图验证工具保护；仅用本地假模型、工具和等待替身。"""

import asyncio
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar, Self, override
from unittest.mock import AsyncMock, Mock

import pytest
from langchain.agents.middleware import ToolRetryMiddleware
from langchain.agents.middleware.types import InputAgentState
from langchain.tools import ToolRuntime
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, ToolException, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import NodeCancelledError
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict

from omt.agent.agent import Agent
from omt.core.bootstrap import build_agent
from omt.core.middlewares.tool_error import ToolErrorMiddleware
from omt.core.middlewares_manager import load_middlewares
from omt.core.tools.read import read
from omt.core.tools.write import write


class ToolModel(FakeMessagesListChatModel):
    """返回预设工具请求及最终回答，不访问真实模型。"""

    @override
    def bind_tools(self, tools: object, **kwargs: object) -> Self:
        return self


class StrictArguments(BaseModel):
    """用严格 schema 验证必填、类型和不支持的参数名。"""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    value: int


@pytest.fixture
def waits(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, AsyncMock]:
    """替换重试模块的等待对象，避免修改全局 asyncio/time 或真实等待。"""
    retry = import_module("langchain.agents.middleware.tool_retry")
    sync_wait = Mock()
    async_wait = AsyncMock()
    monkeypatch.setattr(retry, "time", SimpleNamespace(sleep=sync_wait))
    monkeypatch.setattr(retry, "asyncio", SimpleNamespace(sleep=async_wait))
    return sync_wait, async_wait


def make_agent(operation: BaseTool, args: dict[str, Any]) -> Agent:
    """构造只调用一次工具的假模型，使用统一 middleware 管理入口。"""
    model = ToolModel(responses=[
        AIMessage(content="", tool_calls=[{
            "name": operation.name, "args": args, "id": "call-local", "type": "tool_call",
        }]),
        AIMessage(content="已处理工具结果"),
    ])
    return Agent(model, tools=[operation], middleware=load_middlewares(), checkpointer=InMemorySaver())


def run_agent(agent: Agent, asynchronous: bool) -> dict[str, Any]:
    """经同步或异步公开入口执行完整模型/工具循环。"""
    inputs: InputAgentState = {"messages": [{"role": "user", "content": "调用测试工具"}]}
    config: RunnableConfig = {"configurable": {"thread_id": "middleware-local"}}
    if asynchronous:
        return asyncio.run(agent.ainvoke(inputs, config))
    return agent.invoke(inputs, config)


def tool_result(result: dict[str, Any]) -> ToolMessage:
    """取出关联工具消息，并验证模型循环在错误后仍能完成。"""
    messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert len(messages) == 1
    message = messages[0]
    assert message.tool_call_id == "call-local"
    assert result["messages"][-1].content == "已处理工具结果"
    return message


def test_manager_returns_fresh_prebuilt_retry_policies() -> None:
    first, second = load_middlewares(), load_middlewares()
    assert len(first) == 1 and isinstance(first[0], ToolRetryMiddleware)
    assert first[0] is not second[0]
    policy = first[0]
    assert isinstance(policy, ToolErrorMiddleware)
    assert (policy.max_retries, policy.initial_delay, policy.backoff_factor, policy.max_delay) == (3, 1, 2, 8)
    assert policy.jitter is True


@pytest.fixture
def tool_note(tmp_path: Path) -> Path:
    """为真实读写工具创建隔离文件，用正文和文件状态验证调用结果。"""
    note = tmp_path / "note.txt"
    _ = note.write_text("第一行原始正文\n第二行原始正文\n", encoding="utf-8")
    return note


def assert_builtin_argument_error(
    message: ToolMessage, operation: BaseTool, field: str,
    note: Path, waits: tuple[Mock, AsyncMock],
) -> None:
    """检查参数错误契约：返回修正提示、无正文泄露或文件修改、不等待重试。"""
    assert message.status == "error" and message.name == operation.name
    assert "工具参数错误" in message.content and f"{field}:" in message.content
    assert "请重新调用 tool" in message.content
    assert "原始正文" not in message.content
    assert note.read_text(encoding="utf-8") == "第一行原始正文\n第二行原始正文\n"
    for wait in waits:
        wait.assert_not_called()


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("operation", [read, write], ids=["read", "write"])
def test_builtin_tools_accept_correct_arguments(
    tool_note: Path, operation: BaseTool, asynchronous: bool, waits: tuple[Mock, AsyncMock],
) -> None:
    """正确参数应执行真实工具：read 按偏移返回正文，write 实际覆盖临时文件。"""
    args: dict[str, Any] = {"file": str(tool_note)}
    if operation is read:
        args.update(offset=2, limit=True)
    else:
        args["content"] = "更新后的正文"
    message = tool_result(run_agent(make_agent(operation, args), asynchronous))
    assert message.status == "success" and message.name == operation.name
    if operation is read:
        assert message.content == "第二行原始正文\n"
        assert tool_note.read_text(encoding="utf-8") == "第一行原始正文\n第二行原始正文\n"
    else:
        assert tool_note.read_text(encoding="utf-8") == "更新后的正文"
    for wait in waits:
        wait.assert_not_called()


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_builtin_read_accepts_omitted_optional_arguments(
    tool_note: Path, asynchronous: bool, waits: tuple[Mock, AsyncMock],
) -> None:
    """只提供必填 file 是正确调用，省略 offset/limit 不能被误判为参数过少。"""
    message = tool_result(run_agent(make_agent(read, {"file": str(tool_note)}), asynchronous))
    assert message.status == "success" and message.name == "read"
    assert message.content == "第一行原始正文\n第二行原始正文\n"
    for wait in waits:
        wait.assert_not_called()


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("operation", [read, write], ids=["read", "write"])
@pytest.mark.parametrize("empty", [False, True], ids=["missing-required", "empty-args"])
def test_builtin_tools_reject_insufficient_arguments(
    tool_note: Path, operation: BaseTool, empty: bool,
    asynchronous: bool, waits: tuple[Mock, AsyncMock],
) -> None:
    """参数过少需指出缺失必填项；不能进入读写流程或返回工具执行错误。"""
    args: dict[str, Any] = {}
    if not empty:
        args = {"offset": 1, "limit": False} if operation is read else {"file": str(tool_note)}
    message = tool_result(run_agent(make_agent(operation, args), asynchronous))
    missing_field = "file" if operation is read or empty else "content"
    assert_builtin_argument_error(message, operation, missing_field, tool_note, waits)
    assert "Field required" in message.content


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("operation", [read, write], ids=["read", "write"])
def test_builtin_tools_reject_excess_arguments_before_execution(
    tool_note: Path, operation: BaseTool, asynchronous: bool, waits: tuple[Mock, AsyncMock],
) -> None:
    """提供全部正确参数再额外多传一项，read 不返回正文，write 不覆盖文件。"""
    args: dict[str, Any] = {"file": str(tool_note), "nonexistent_param": "probe"}
    if operation is read:
        args.update(offset=1, limit=False)
    else:
        args["content"] = "不应写入的正文"
    message = tool_result(run_agent(make_agent(operation, args), asynchronous))
    assert_builtin_argument_error(message, operation, "nonexistent_param", tool_note, waits)
    assert "Extra inputs are not permitted" in message.content


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("operation", [read, write], ids=["read", "write"])
@pytest.mark.parametrize("mismatch", ["wrong-name", "wrong-type"])
def test_builtin_tools_reject_mismatched_arguments(
    tool_note: Path, operation: BaseTool, mismatch: str,
    asynchronous: bool, waits: tuple[Mock, AsyncMock],
) -> None:
    """参数数量不变时，拼错参数名或传入不匹配的类型也必须返回参数修正提示。"""
    args: dict[str, Any] = {"file": str(tool_note)}
    if operation is read:
        args.update(offset=1, limit=False)
        if mismatch == "wrong-name":
            args["path"] = args.pop("file")
            field = "path"
        else:
            args["offset"] = "not-an-integer"
            field = "offset"
    elif mismatch == "wrong-name":
        args["text"] = "不应写入的正文"
        field = "text"
    else:
        args["content"] = {"unexpected": "not-a-string"}
        field = "content"
    message = tool_result(run_agent(make_agent(operation, args), asynchronous))
    assert_builtin_argument_error(message, operation, field, tool_note, waits)
    if mismatch == "wrong-name":
        assert "Extra inputs are not permitted" in message.content
    elif operation is read:
        assert "valid integer" in message.content
    else:
        assert "valid string" in message.content


@pytest.mark.parametrize("asynchronous", [False, True])
def test_default_schema_rejects_extra_arguments_without_executing_tool(
    asynchronous: bool, waits: tuple[Mock, AsyncMock],
) -> None:
    """默认 @tool 未配置 extra=forbid 时，middleware 仍须挡住多个未知字段。"""
    executed: list[int] = []

    @tool
    def operation(value: int) -> str:
        """记录执行副作用，确认未知字段被拒绝时根本没有进入工具体。"""
        executed.append(value)
        return "成功"

    message = tool_result(run_agent(make_agent(operation, {
        "value": 1, "unknown_b": "private-b", "unknown_a": "private-a",
    }), asynchronous))
    assert message.status == "error" and message.name == "operation"
    assert "unknown_a: Extra inputs are not permitted；unknown_b: Extra inputs are not permitted" in message.content
    assert "private-a" not in message.content and "private-b" not in message.content
    assert "请重新调用 tool" in message.content
    assert executed == []
    for wait in waits:
        wait.assert_not_called()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("allow_extra", [False, True])
def test_json_schema_extra_field_policy_is_respected(
    asynchronous: bool, allow_extra: bool, waits: tuple[Mock, AsyncMock],
) -> None:
    """MCP 风格 JSON schema 的封闭字段需拒绝，显式开放的动态字段仍可传入。"""
    executed: list[dict[str, Any]] = []

    @tool(args_schema={
        "type": "object", "properties": {"value": {"type": "integer"}},
        "additionalProperties": allow_extra,
    })
    def operation(value: int, **kwargs: Any) -> str:
        """使用字典 schema 的本地工具，不连接任何 MCP 服务。"""
        executed.append(kwargs)
        return f"成功：{value}"

    message = tool_result(run_agent(make_agent(operation, {"value": 1, "dynamic": 2}), asynchronous))
    if allow_extra:
        assert message.status == "success" and message.content == "成功：1"
        assert executed == [{"dynamic": 2}]
    else:
        assert message.status == "error" and "dynamic" in message.content
        assert executed == []
    for wait in waits:
        wait.assert_not_called()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("args", [{}, {"value": "not-an-integer"}, {"value": 1, "unknown": 2}])
def test_argument_errors_return_correction_template_without_retry(
    args: dict[str, Any], asynchronous: bool, waits: tuple[Mock, AsyncMock],
) -> None:
    executed: list[int] = []

    @tool(args_schema=StrictArguments)
    def operation(value: int) -> str:
        """接收一个整数；校验失败不得进入工具体。"""
        executed.append(value)
        return "成功"

    original_handler = operation.handle_validation_error
    message = tool_result(run_agent(make_agent(operation, args), asynchronous))
    assert message.status == "error" and message.name == "operation"
    assert "工具参数错误" in message.content and "请重新调用 tool" in message.content
    assert executed == []
    assert operation.handle_validation_error is original_handler
    for wait in waits:
        wait.assert_not_called()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("exception_type", [RuntimeError, TypeError, ToolException])
@pytest.mark.parametrize("jitter_edge", [-1, 1])
def test_tool_errors_retry_three_times_with_exponential_jitter_then_return_error(
    asynchronous: bool, exception_type: type[Exception], jitter_edge: int,
    waits: tuple[Mock, AsyncMock], monkeypatch: pytest.MonkeyPatch,
) -> None:
    def jitter_value(low: float, high: float) -> float:
        """固定抖动上下界，验证实际等待而非只核对配置。"""
        return low if jitter_edge < 0 else high

    monkeypatch.setattr("langchain.agents.middleware._retry.random.uniform", jitter_value)
    attempts: list[int] = []

    @tool
    def operation(value: int) -> str:
        """模拟工具内部故障；内部 TypeError 不应被误判为调用参数问题。"""
        attempts.append(value)
        raise exception_type("测试工具故障")

    # 模拟 MCP 适配器预设的工具异常处理器；统一策略仍必须能看到并重试异常。
    operation.handle_tool_error = True
    message = tool_result(run_agent(make_agent(operation, {"value": 7}), asynchronous))
    assert operation.handle_tool_error is True
    assert attempts == [7] * 4
    assert message.status == "error"
    assert message.content == f"工具错误：{exception_type.__name__}: 测试工具故障"
    assert "请重新调用" not in message.content
    active_wait, inactive_wait = (waits[1], waits[0]) if asynchronous else waits
    assert [call.args[0] for call in active_wait.call_args_list] == [base * (1 + jitter_edge * 0.25) for base in (1, 2, 4)]
    assert all(call.args[0] <= 8 for call in active_wait.call_args_list)
    inactive_wait.assert_not_called()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("failures", [0, 2, 3])
def test_success_stops_retry_and_preserves_injected_runtime(
    asynchronous: bool, failures: int, waits: tuple[Mock, AsyncMock],
) -> None:
    attempts: list[int] = []

    @tool
    def operation(value: int, runtime: ToolRuntime) -> str:
        """校验注入参数仍可用，并在指定次数故障后返回正常结果。"""
        assert runtime.tool_call_id == "call-local"
        attempts.append(value)
        if len(attempts) <= failures:
            raise OSError("暂时不可用")
        return f"成功：{value}"

    message = tool_result(run_agent(make_agent(operation, {"value": 9}), asynchronous))
    assert message.status == "success" and message.content == "成功：9"
    assert attempts == [9] * (failures + 1)
    active_wait = waits[1] if asynchronous else waits[0]
    assert active_wait.call_count == failures


def test_async_tool_and_cancellation_are_not_swallowed(waits: tuple[Mock, AsyncMock]) -> None:
    attempts: list[int] = []

    @tool
    async def operation(value: int) -> str:
        """模拟异步工具被取消，不把取消当作工具错误重试。"""
        attempts.append(value)
        raise asyncio.CancelledError()

    # LangGraph 在图边界将工具内取消包装为 NodeCancelledError，middleware 不应拦截。
    with pytest.raises(NodeCancelledError) as raised:
        _ = run_agent(make_agent(operation, {"value": 1}), True)
    assert isinstance(raised.value.__cause__, asyncio.CancelledError)
    assert attempts == [1]
    for wait in waits:
        wait.assert_not_called()


@pytest.mark.parametrize("asynchronous", [False, True])
def test_graph_interrupt_is_not_retried(asynchronous: bool, waits: tuple[Mock, AsyncMock]) -> None:
    @tool
    def operation(value: int) -> str:
        """发出图暂停信号，不应被当作执行异常。"""
        return str(interrupt(f"确认 {value}"))

    result = run_agent(make_agent(operation, {"value": 1}), asynchronous)
    assert result["__interrupt__"][0].value == "确认 1"
    assert not any(isinstance(message, ToolMessage) for message in result["messages"])
    for wait in waits:
        wait.assert_not_called()


def test_async_only_tool_recovers_after_retry(waits: tuple[Mock, AsyncMock]) -> None:
    attempts: list[int] = []

    @tool
    async def operation(value: int) -> str:
        """纯异步工具首轮失败后恢复，不依赖同步工具线程。"""
        attempts.append(value)
        if len(attempts) == 1:
            raise OSError("临时错误")
        return "异步成功"

    message = tool_result(run_agent(make_agent(operation, {"value": 2}), True))
    assert message.status == "success" and message.content == "异步成功"
    assert attempts == [2, 2]
    assert waits[1].await_count == 1
    waits[0].assert_not_called()


def test_bootstrap_installs_error_policy_for_extra_tools(waits: tuple[Mock, AsyncMock]) -> None:
    @tool
    def operation(value: int) -> str:
        """用于确认应用组装入口实际安装了参数错误保护。"""
        return str(value)

    wrapped_model = Mock()
    wrapped_model.model = ToolModel(responses=[
        AIMessage(content="", tool_calls=[{"name": "operation", "args": {}, "id": "call-local", "type": "tool_call"}]),
        AIMessage(content="已处理工具结果"),
    ])
    agent = asyncio.run(build_agent(wrapped_model, extra_tools=[operation]))
    message = tool_result(run_agent(agent, True))
    assert message.status == "error" and "请重新调用 tool" in message.content
    for wait in waits:
        wait.assert_not_called()
