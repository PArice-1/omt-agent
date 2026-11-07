import json
import unittest
from unittest.mock import create_autospec

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from rag_mcp.mcp import KnowledgeBase
from rag_mcp.mcp.tools import register_tools


class ToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.kb = create_autospec(KnowledgeBase, instance=True)
        self.server = MCPServer("tools-test")
        register_tools(self.server, self.kb)

    async def invoke(self, name, arguments):
        result = await self.server.call_tool(name, arguments)
        self.assertEqual(len(result.content), 1)
        self.assertEqual(result.content[0].type, "text")
        return json.loads(result.content[0].text)

    async def test_semantic_search_forwards_all_parameters_and_preserves_unicode(self):
        self.kb.search.return_value = [{"text": "中文正文", "score": 0.9}]
        result = await self.invoke("search_knowledge", {
            "text": "如何安装？", "limit": 10, "source": "/资料/a.md", "min_score": 0.5,
        })
        self.kb.search.assert_called_once_with("如何安装？", limit=10, source="/资料/a.md", min_score=0.5)
        self.assertEqual(result, [{"text": "中文正文", "score": 0.9}])

    async def test_semantic_search_defaults_and_empty_results(self):
        self.kb.search.return_value = []
        self.assertEqual(await self.invoke("search_knowledge", {"text": "问题"}), [])
        self.kb.search.assert_called_once_with("问题", limit=5, source=None, min_score=None)

    async def test_keyword_search_forwards_pagination_and_source(self):
        self.kb.keyword_search.return_value = {"items": [], "has_more": False}
        await self.invoke("search_keyword", {"text": "ERROR42", "limit": 2, "offset": 3, "source": "/a.txt"})
        self.kb.keyword_search.assert_called_once_with("ERROR42", limit=2, offset=3, source="/a.txt")

    async def test_list_documents_forwards_pagination(self):
        self.kb.list_documents.return_value = {"items": [], "total": 0}
        await self.invoke("list_documents", {"limit": 3, "offset": 5})
        self.kb.list_documents.assert_called_once_with(limit=3, offset=5)

    async def test_get_document_forwards_source_version_and_ingestion(self):
        self.kb.get_document.return_value = {"items": [{"text": "正文"}]}
        result = await self.invoke("get_document", {
            "source": "/a.md", "processing_key": "key", "ingestion_id": "run", "limit": 2, "offset": 1,
        })
        self.kb.get_document.assert_called_once_with(
            "/a.md", processing_key="key", ingestion_id="run", limit=2, offset=1,
        )
        self.assertEqual(result["items"][0]["text"], "正文")

    async def test_get_chunk_returns_null_when_missing(self):
        self.kb.get_chunk.return_value = None
        self.assertIsNone(await self.invoke("get_chunk", {"chunk_id": "id"}))
        self.kb.get_chunk.assert_called_once_with("id")

    async def test_stats_forwards_without_arguments(self):
        self.kb.stats.return_value = {"exists": False, "chunk_count": 0}
        self.assertEqual(await self.invoke("get_knowledge_base_stats", {}), self.kb.stats.return_value)
        self.kb.stats.assert_called_once_with()

    async def test_invalid_numbers_are_not_serialized_as_json_nan(self):
        self.kb.search.return_value = [{"score": float("nan")}]
        with self.assertRaisesRegex(ToolError, "not JSON compliant"):
            await self.server.call_tool("search_knowledge", {"text": "问题"})

    async def test_errors_are_left_to_mcp_instead_of_wrapped_as_success_payload(self):
        self.kb.search.side_effect = ValueError("模型配置不匹配")
        with self.assertRaisesRegex(ToolError, "模型配置不匹配"):
            await self.server.call_tool("search_knowledge", {"text": "问题"})


if __name__ == "__main__":
    unittest.main()
