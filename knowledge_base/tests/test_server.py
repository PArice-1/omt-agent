import asyncio
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mcp import Client, StdioServerParameters, stdio_client

from rag_mcp import main as package_main
from rag_mcp.build_kb import build_kb
from rag_mcp.chunk.rules import DEFAULT_CHUNK_SIZE
from rag_mcp.config import DEFAULT_COLLECTION, DEFAULT_DB_PATH
from rag_mcp.mcp import KnowledgeBase
from rag_mcp.mcp.server import create_server, main


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_six_read_only_tools_are_registered_with_expected_schemas(self):
        server = create_server()
        tools = {tool.name: tool for tool in await server.list_tools()}
        self.assertEqual(set(tools), {
            "search_knowledge", "search_keyword", "list_documents", "get_document", "get_chunk",
            "get_knowledge_base_stats",
        })
        search = tools["search_knowledge"]
        self.assertEqual(search.input_schema["properties"]["text"]["type"], "string")
        self.assertIn("text", search.input_schema["required"])
        self.assertEqual(search.input_schema["properties"]["limit"]["default"], 5)
        for tool in tools.values():
            self.assertTrue(tool.annotations.read_only_hint)
            self.assertFalse(tool.annotations.destructive_hint)
            self.assertTrue(tool.description)

    async def test_server_creation_has_no_filesystem_or_model_side_effects(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "not-created"
            with (
                patch("rag_mcp.chunk.Chunker.chunk", side_effect=AssertionError("不能切分")),
                patch("rag_mcp.embed.ollama.embed_text", side_effect=AssertionError("不能请求模型")),
                patch("rag_mcp.mcp.knowledge_base.VectorDatabase", side_effect=AssertionError("不能打开数据库")),
            ):
                server = create_server(path)
                self.assertEqual(len(await server.list_tools()), 6)
            self.assertFalse(path.exists())

    async def test_build_multiple_roots_then_search_and_read_via_mcp(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "one", root / "two"
            first.mkdir()
            second.mkdir()
            (first / "guide.md").write_text("# 安装\n运行 Python 创建环境。", encoding="utf-8")
            (second / "notes.txt").write_text("错误码 ERROR42 的处理方法。", encoding="utf-8")
            db_path = root / "db"
            with patch("rag_mcp.embed.embeder.embed_text", return_value=[1.0, 0.0, 0.0]) as embed:
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(build_kb([str(first), second], db_path=db_path, collection_name="docs"), 2)
                self.assertEqual(embed.call_count, 2)
            server = create_server(db_path, "docs")
            with (
                patch("rag_mcp.chunk.Chunker.chunk", side_effect=AssertionError("搜索不应切分")),
                patch("rag_mcp.embed.ollama.embed_text", return_value=[1.0, 0.0, 0.0]) as query_embed,
            ):
                result = await server.call_tool("search_knowledge", {"text": "创建环境", "source": str(first / "guide.md")})
                self.assertFalse(result.is_error)
                found = json.loads(result.content[0].text)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["text"], "运行 Python 创建环境。")
                chunk = await server.call_tool("get_chunk", {"chunk_id": found[0]["id"]})
                self.assertEqual(json.loads(chunk.content[0].text)["text"], found[0]["text"])
                keyword = await server.call_tool("search_keyword", {"text": "ERROR42"})
                self.assertEqual(len(json.loads(keyword.content[0].text)["items"]), 1)
                stats = await server.call_tool("get_knowledge_base_stats", {})
                self.assertEqual(json.loads(stats.content[0].text)["chunk_count"], 2)
                self.assertEqual(query_embed.call_count, 1)
                # 同一服务的工具可能在线程池中并发运行，数据库访问必须串行打开/关闭。
                parallel = await asyncio.gather(*(
                    server.call_tool("get_knowledge_base_stats", {}) for _ in range(4)
                ))
                self.assertTrue(all(not result.is_error for result in parallel))

    async def test_missing_database_returns_empty_results_not_protocol_errors(self):
        with TemporaryDirectory() as directory:
            server = create_server(Path(directory) / "missing")
            result = await server.call_tool("search_knowledge", {"text": "问题"})
            self.assertFalse(result.is_error)
            self.assertEqual(json.loads(result.content[0].text), [])

    async def test_real_stdio_server_handshake_tools_and_error_result(self):
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "missing"
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "rag_mcp.mcp.server", "--db-path", str(db_path)],
            )
            async with asyncio.timeout(30), Client(stdio_client(params), mode="legacy") as client:
                tools = await client.list_tools()
                self.assertEqual(len(tools.tools), 6)
                stats = await client.call_tool("get_knowledge_base_stats", {})
                self.assertFalse(stats.is_error)
                self.assertFalse(json.loads(stats.content[0].text)["exists"])
                invalid = await client.call_tool("search_knowledge", {"text": "问题", "limit": 0})
                self.assertTrue(invalid.is_error)
                self.assertIn("limit", invalid.content[0].text)
                self.assertFalse(db_path.exists())

    @patch("rag_mcp.mcp.server.create_server")
    def test_server_cli_passes_storage_and_collection_and_uses_stdio(self, create):
        with patch("sys.argv", ["rag-mcp", "--db-path", "./db", "--collection", "docs"]):
            main()
        create.assert_called_once_with("./db", "docs")
        create.return_value.run.assert_called_once_with(transport="stdio")

    @patch("rag_mcp.mcp.server.build_kb")
    @patch("rag_mcp.mcp.server.create_server")
    def test_startup_build_uses_defaults_before_starting_server(self, create, build):
        def build_before_create(*args, **kwargs):
            create.assert_not_called()
            print("构建进度")

        build.side_effect = build_before_create
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch("sys.argv", ["rag-mcp", "--build-on-start"]),
            redirect_stdout(stdout), redirect_stderr(stderr),
        ):
            main()
        build.assert_called_once_with(
            ["./knowledge-base"], db_path=str(DEFAULT_DB_PATH),
            collection_name=DEFAULT_COLLECTION, chunk_size=DEFAULT_CHUNK_SIZE,
        )
        create.assert_called_once_with(str(DEFAULT_DB_PATH), DEFAULT_COLLECTION)
        create.return_value.run.assert_called_once_with(transport="stdio")
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    @patch("rag_mcp.mcp.server.build_kb")
    @patch("rag_mcp.mcp.server.create_server")
    def test_startup_build_forwards_multiple_sources_and_settings(self, create, build):
        with patch("sys.argv", [
            "rag-mcp", "--build-on-start", "--source", "./docs", "./notes.txt",
            "--db-path", "./db", "--collection", "docs", "--chunk-size", "1000",
        ]):
            main()
        build.assert_called_once_with(
            ["./docs", "./notes.txt"], db_path="./db", collection_name="docs", chunk_size=1000,
        )
        create.assert_called_once_with("./db", "docs")

    @patch("rag_mcp.mcp.server.build_kb")
    @patch("rag_mcp.mcp.server.create_server")
    def test_startup_without_build_flag_does_not_build(self, create, build):
        with patch("sys.argv", ["rag-mcp"]):
            main()
        build.assert_not_called()
        create.return_value.run.assert_called_once_with(transport="stdio")

    @patch("rag_mcp.mcp.server.build_kb", side_effect=RuntimeError("构建失败"))
    @patch("rag_mcp.mcp.server.create_server")
    def test_failed_startup_build_does_not_start_server(self, create, build):
        original_stdout = sys.stdout
        with patch("sys.argv", ["rag-mcp", "--build-on-start"]):
            with self.assertRaisesRegex(RuntimeError, "构建失败"):
                main()
        create.assert_not_called()
        self.assertIs(sys.stdout, original_stdout)

    @patch("rag_mcp.mcp.server.create_server")
    def test_source_without_build_flag_is_rejected(self, create):
        with (
            patch("sys.argv", ["rag-mcp", "--source", "./docs"]),
            redirect_stderr(io.StringIO()) as stderr,
            self.assertRaises(SystemExit) as error,
        ):
            main()
        self.assertEqual(error.exception.code, 2)
        self.assertIn("--build-on-start", stderr.getvalue())
        create.assert_not_called()

    def test_startup_build_is_incremental_and_releases_database_before_serving(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "docs"
            source.mkdir()
            first = source / "first.md"
            first.write_text("# 安装\n初始内容。", encoding="utf-8")
            db_path = source / "storage"
            kb = KnowledgeBase(db_path, "docs")
            counts = []

            def read_database_before_serving(*args, **kwargs):
                counts.append(kb.stats()["chunk_count"])
                return create_server(*args, **kwargs)

            argv = ["rag-mcp", "--build-on-start", "--source", str(source),
                    "--db-path", str(db_path), "--collection", "docs"]
            with (
                patch("sys.argv", argv), redirect_stderr(io.StringIO()),
                redirect_stdout(io.StringIO()) as stdout,
                patch("rag_mcp.mcp.server.create_server", side_effect=read_database_before_serving),
                patch("rag_mcp.mcp.server.MCPServer.run"),
                patch("rag_mcp.embed.embeder.embed_text", return_value=[1.0, 0.0, 0.0]) as embed,
            ):
                main()
                self.assertEqual(embed.call_count, 1)
                with patch("rag_mcp.chunk.Chunker.chunk", side_effect=AssertionError("未变化不应切分")):
                    main()
                self.assertEqual(embed.call_count, 1)
                first.write_text("# 安装\n更新内容。", encoding="utf-8")
                (source / "second.txt").write_text("新增文件。", encoding="utf-8")
                main()
                self.assertEqual(embed.call_count, 3)
            self.assertEqual(counts, [1, 1, 3])
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(kb.keyword_search("更新内容")["items"][0]["text"], "更新内容。")

    async def test_startup_build_preserves_real_stdio_protocol(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "docs"
            source.mkdir()
            db_path = root / "db"
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "rag_mcp.mcp.server", "--build-on-start",
                      "--source", str(source), "--db-path", str(db_path)],
            )
            # stdio_client 需要真实文件描述符，确认子进程没有输出构建进度。
            with (root / "stderr.log").open("w+", encoding="utf-8") as error_log:
                async with asyncio.timeout(30), Client(
                    stdio_client(params, errlog=error_log), mode="legacy",
                ) as client:
                    tools = await client.list_tools()
                    self.assertEqual(len(tools.tools), 6)
                    stats = await client.call_tool("get_knowledge_base_stats", {})
                    self.assertFalse(stats.is_error)
                    self.assertFalse(json.loads(stats.content[0].text)["exists"])
                error_log.seek(0)
                self.assertEqual(error_log.read(), "")
            self.assertFalse(db_path.exists())

    @patch("rag_mcp.mcp.server.main")
    def test_package_entrypoint_starts_server(self, serve):
        package_main()
        serve.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
