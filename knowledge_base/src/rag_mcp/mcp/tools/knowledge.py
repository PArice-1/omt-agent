"""知识库状态工具。"""

from mcp.server import MCPServer

from ..knowledge_base import KnowledgeBase
from ._shared import READ_ONLY, as_json


def register_knowledge_tools(server: MCPServer, kb: KnowledgeBase) -> None:
    @server.tool(annotations=READ_ONLY, structured_output=False)
    def get_knowledge_base_stats() -> str:
        """读取知识库集合是否存在、向量维度、模型、片段数、来源数和文档写入完整性；
        不调用模型，也不创建不存在的数据库。"""
        return as_json(kb.stats())
