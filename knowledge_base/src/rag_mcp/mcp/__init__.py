"""持久化知识库读取与 MCP 服务；导入时不启动服务或打开数据库。"""

from .knowledge_base import KnowledgeBase

__all__ = ["KnowledgeBase"]
