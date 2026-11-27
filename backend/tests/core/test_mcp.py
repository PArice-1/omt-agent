"""MCP 可选发现：通过真实适配客户端与工具加载替身验证失败隔离，不启动外部服务。"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.sessions import Connection

from omt.core.mcp import get_tools


def _tool(name: str) -> BaseTool:
    """创建可直接调用的离线工具，返回固定内容以验证成功结果仍可用。"""
    return StructuredTool.from_function(
        func=lambda: "离线检索结果", name=name, description="测试专用检索工具",
    )


@pytest.mark.parametrize("outcomes, expected_names", [
    (["first_search", "second_search"], ["first_search", "second_search"]),
    ([ConnectionError("test-only-token"), "second_search"], ["second_search"]),
    (["first_search", TimeoutError("test-only-token")], ["first_search"]),
    ([FileNotFoundError("test-only-token"), RuntimeError("test-only-token")], []),
    ([ExceptionGroup("连接失败", [OSError("test-only-token")]), "second_search"], ["second_search"]),
])
def test_discovery_keeps_healthy_tools_when_servers_fail(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    outcomes: list[str | Exception], expected_names: list[str],
) -> None:
    """单个或全部服务不可用时只跳过失败项，不能丢弃正常工具或泄露连接异常内容。"""
    loader = AsyncMock(side_effect=[
        [_tool(item)] if isinstance(item, str) else item for item in outcomes
    ])
    monkeypatch.setattr("langchain_mcp_adapters.client.load_mcp_tools", loader)
    servers: dict[str, Connection] = {
        "first": {"transport": "stdio", "command": "test-only-first", "args": []},
        "second": {"transport": "stdio", "command": "test-only-second", "args": []},
    }

    tools = asyncio.run(get_tools(servers))

    assert [tool.name for tool in tools] == expected_names
    assert all(tool.invoke({}) == "离线检索结果" for tool in tools)
    assert "test-only-token" not in caplog.text


def test_empty_servers_return_no_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """没有配置 MCP 时不进行任何工具发现。"""
    loader = AsyncMock(side_effect=AssertionError("不应加载 MCP"))
    monkeypatch.setattr("langchain_mcp_adapters.client.load_mcp_tools", loader)

    assert asyncio.run(get_tools({})) == []
    loader.assert_not_awaited()


def test_discovery_does_not_swallow_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    """取消不是可选插件故障，必须让应用按正常退出流程处理。"""
    loader = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr("langchain_mcp_adapters.client.load_mcp_tools", loader)

    with pytest.raises(asyncio.CancelledError):
        _ = asyncio.run(get_tools({"cancelled": {"transport": "stdio", "command": "test-only", "args": []}}))
