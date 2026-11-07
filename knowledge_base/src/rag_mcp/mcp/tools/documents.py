"""文档目录和已入库片段的读取工具，不读取任意磁盘路径。"""

from mcp.server import MCPServer

from ..knowledge_base import KnowledgeBase
from ._shared import READ_ONLY, as_json


def register_document_tools(server: MCPServer, kb: KnowledgeBase) -> None:
    @server.tool(annotations=READ_ONLY, structured_output=False)
    def list_documents(limit: int = 50, offset: int = 0) -> str:
        """分页列出知识库文档的来源、处理标识、写入批次及是否完整。
        一个来源的不同版本和重试批次分别列出。limit 为 1–100，offset 从 0 开始。"""
        return as_json(kb.list_documents(limit=limit, offset=offset))

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def get_document(
        source: str,
        processing_key: str | None = None,
        ingestion_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> str:
        """分页读取指定来源的已入库片段，按版本、批次和原文位置排序，不直接读取磁盘文件。
        source 使用列表/搜索返回的绝对路径；可传 processing_key 和 ingestion_id 锁定版本/批次，
        不指定则包含所有历史版本。limit 为 1–100，offset 从 0 开始。"""
        return as_json(kb.get_document(
            source, processing_key=processing_key, ingestion_id=ingestion_id, limit=limit, offset=offset,
        ))

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def get_chunk(chunk_id: str) -> str:
        """根据搜索结果中的 id 精确读取一个已入库片段及其来源、标题和定位；不存在返回 null。"""
        return as_json(kb.get_chunk(chunk_id))
