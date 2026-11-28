import asyncio
import logging

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.sessions import Connection


logger = logging.getLogger(__name__)


async def get_tools(
    servers: dict[str, Connection],
) -> list[BaseTool]:
    """并发发现可用 MCP 工具，连接生命周期由适配库管理。

    servers 按服务名提供连接配置，空映射返回空列表。单个服务初始化或工具发现
    失败时跳过该服务，保留其他工具及服务名前缀；取消和进程退出信号继续传播。
    警告仅记录服务名和异常类型，不输出可能含凭据的连接配置或异常原文。
    """

    async def load_server(name: str, connection: Connection) -> list[BaseTool]:
        """独立加载一个可选服务，将普通连接或协议异常降级为空工具列表。"""
        try:
            client = MultiServerMCPClient({name: connection}, tool_name_prefix=True)
            return await client.get_tools(server_name=name)
        except Exception as exc:
            logger.warning("MCP 服务 %r 不可用，已跳过（%s）", name, type(exc).__name__)
            return []

    results = await asyncio.gather(*(load_server(name, connection) for name, connection in servers.items()))
    return [tool for tools in results for tool in tools]
