"""语义搜索和精确关键词搜索工具。"""

from mcp.server import MCPServer

from ..knowledge_base import KnowledgeBase
from ._shared import READ_ONLY, as_json


def register_search_tools(server: MCPServer, kb: KnowledgeBase) -> None:
    @server.tool(annotations=READ_ONLY, structured_output=False)
    def search_knowledge(
        text: str, limit: int = 5, source: str | None = None, min_score: float | None = None
    ) -> str:
        """语义搜索知识库，返回片段 ID、正文、来源、定位和相似度。limit 为 1–100；
        source 可限定已入库的绝对路径；min_score 可限定 -1 到 1 的最低得分。
        只生成问题向量，不重建知识库。"""
        return as_json(kb.search(text, limit=limit, source=source, min_score=min_score))

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def search_keyword(
        text: str, limit: int = 20, offset: int = 0, source: str | None = None
    ) -> str:
        """在已入库标题和正文中做不区分大小写的子串匹配，适合函数名、错误码等精确查询。
        不调用模型；按片段 ID 而非相关度排序。limit 为 1–100，offset 为匹配结果的跳过条数。"""
        return as_json(kb.keyword_search(text, limit=limit, offset=offset, source=source))
