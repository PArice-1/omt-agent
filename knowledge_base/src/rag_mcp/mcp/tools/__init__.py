"""按功能组织 MCP 工具，所有工具共用同一个知识库实例。"""

from mcp.server import MCPServer

from ..knowledge_base import KnowledgeBase
from .documents import register_document_tools
from .knowledge import register_knowledge_tools
from .search import register_search_tools


def register_tools(server: MCPServer, kb: KnowledgeBase) -> None:
    register_search_tools(server, kb)
    register_document_tools(server, kb)
    register_knowledge_tools(server, kb)


__all__ = ["register_tools"]
