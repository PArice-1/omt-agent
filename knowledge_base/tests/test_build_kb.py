import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rag_mcp.build_kb import build_kb, main
from rag_mcp.chunk import Chunker
from rag_mcp.embed import Embed, EmbedMetadata
from rag_mcp.fliter import Fliter
from rag_mcp.vector_databbase import VectorDatabase


def embedding_response():
    return io.BytesIO(json.dumps({"embeddings": [[1.0, 0.0, 0.0]]}).encode())


class BuildKnowledgeBaseTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.db_path = self.root / "storage"
        self.output = io.StringIO()
        self.enterContext(redirect_stdout(self.output))
        self.urlopen = self.enterContext(patch("rag_mcp.embed.ollama.urlopen"))
        self.urlopen.side_effect = lambda *args, **kwargs: embedding_response()

    def write(self, name="notes.txt", text="正文。"):
        file = self.root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
        return file

    def build(self, paths=None, **kwargs):
        return build_kb([self.root] if paths is None else paths, db_path=self.db_path, **kwargs)

    def test_build_persistent_database_and_exclude_storage(self):
        self.write("guide.md", "# 指南\n安装步骤。\n")
        self.write("notes.txt", "补充说明。")
        self.write("storage/ignored.md", "不要入库。")
        self.assertEqual(self.build(), 2)
        self.assertEqual(self.urlopen.call_count, 2)
        with VectorDatabase(self.db_path) as db:
            points, _ = db.client.scroll("knowledge", limit=10, with_payload=True)
            payloads = {point.payload["text"]: point.payload for point in points}
            self.assertEqual(set(payloads), {"安装步骤。\n", "补充说明。"})
            self.assertEqual(payloads["安装步骤。\n"]["heading_path"], ["指南"])
            self.assertEqual(payloads["补充说明。"]["source"], str(self.root / "notes.txt"))
        self.assertIn("持久化验证通过", self.output.getvalue())

    def test_multiple_directories_mixed_files_and_overlapping_paths_share_one_database(self):
        first = self.write("one/a.md", "# 标题\n第一份正文")
        second = self.write("two/b.txt", "第二份正文")
        self.write("two/copy.md", first.read_text(encoding="utf-8"))
        paths = [str(first.parent), second.parent, first, str(second), self.root / "one"]
        with patch.object(Chunker, "chunk", wraps=Chunker().chunk) as chunk:
            self.assertEqual(self.build(paths), 2)
            chunk.assert_called_once_with([first, second])
        with patch.object(Chunker, "chunk", side_effect=AssertionError("不应重复切分")):
            self.assertEqual(self.build(paths), 0)
        self.assertEqual(self.urlopen.call_count, 2)
        self.assertFalse((first.parent / "storage").exists())
        self.assertFalse((second.parent / "storage").exists())

    def test_explicit_files_only_import_selected_files(self):
        first = self.write("one/a.txt", "指定正文")
        self.write("one/ignored.txt", "不应入库")
        second = self.write("two/b.md", "# 标题\n另一份正文")
        self.assertEqual(self.build([str(first), second]), 2)
        self.assertEqual(self.urlopen.call_count, 2)

    def test_invalid_inputs_fail_before_model_or_database_creation(self):
        valid = self.write()
        unsupported = self.write("bad.pdf")
        for paths, error in (
            (self.root, TypeError), (str(self.root), TypeError), ([None], TypeError),
            ([valid, self.root / "missing"], FileNotFoundError), ([unsupported], ValueError),
        ):
            with self.subTest(paths=paths), self.assertRaises(error):
                self.build(paths)
        self.urlopen.assert_not_called()
        self.assertFalse(self.db_path.exists())

    def test_empty_file_skips_model_and_database(self):
        self.write("empty.md", "# 空章节\n")
        self.assertEqual(self.build(), 0)
        self.assertFalse(self.db_path.exists())
        self.urlopen.assert_not_called()

    def test_empty_paths_or_empty_directory_skip_chunker_model_and_database(self):
        with patch.object(Chunker, "chunk", side_effect=AssertionError("不应切分")):
            self.assertEqual(self.build([]), 0)
            self.assertEqual(self.build(), 0)
        self.assertFalse(self.db_path.exists())
        self.urlopen.assert_not_called()

    def test_repeated_build_skips_chunker_and_model(self):
        self.write()
        self.assertEqual(self.build(), 1)
        with patch.object(Chunker, "chunk", side_effect=AssertionError("不应重复切分")):
            self.assertEqual(self.build(), 0)
        self.assertEqual(self.urlopen.call_count, 1)
        with VectorDatabase(self.db_path) as db:
            self.assertEqual(db.client.count("knowledge", exact=True).count, 1)
            points, _ = db.client.scroll("knowledge", with_payload=True)
            self.assertIn("processing_key", points[0].payload)
            self.assertEqual(points[0].payload["chunk_count"], 1)

    def test_identical_files_in_batch_and_renamed_copy_are_filtered(self):
        first = self.write("a.md", "# 指南\n正文。")
        second = self.write("b.md", first.read_text(encoding="utf-8"))
        with patch.object(Chunker, "chunk", wraps=Chunker().chunk) as chunk:
            self.assertEqual(self.build(), 1)
            chunk.assert_called_once_with([first])
        first.unlink()
        second.rename(self.root / "renamed.md")
        with patch.object(Chunker, "chunk", side_effect=AssertionError("不应切分副本")):
            self.assertEqual(self.build(), 0)
        self.assertEqual(self.urlopen.call_count, 1)

    def test_modified_file_appends_new_version_then_skips(self):
        file = self.write("notes.md", "# 标题\n原始正文。")
        self.assertEqual(self.build(), 1)
        file.write_text("# 标题\n修改后的正文。", encoding="utf-8")
        self.assertEqual(self.build(), 1)
        self.assertEqual(self.build(), 0)
        self.assertEqual(self.urlopen.call_count, 2)
        with VectorDatabase(self.db_path) as db:
            self.assertEqual(db.client.count("knowledge", exact=True).count, 2)

    def test_collections_are_isolated(self):
        self.write()
        self.assertEqual(self.build(collection_name="first"), 1)
        self.assertEqual(self.build(collection_name="second"), 1)
        self.assertEqual(self.build(collection_name="first"), 0)
        self.assertEqual(self.urlopen.call_count, 2)

    def test_legacy_records_are_rebuilt_once_without_deleting_history(self):
        file = self.write("notes.md", "# 标题\n历史正文。")
        chunks = Chunker().chunk(file)
        embeds = [
            Embed([1.0, 0.0, 0.0], EmbedMetadata(**vars(chunk.metadata), text=chunk.text))
            for chunk in chunks
        ]
        with VectorDatabase(self.db_path) as db:
            db.create_collection("knowledge", 3)
            db.upsert("knowledge", embeds)
            db.upsert("knowledge", embeds)
        file.rename(self.root / "renamed.md")
        self.assertEqual(self.build(), 1)
        with patch.object(Chunker, "chunk", side_effect=AssertionError("不应再次切分")):
            self.assertEqual(self.build(), 0)
        self.assertEqual(self.urlopen.call_count, 1)
        with VectorDatabase(self.db_path) as db:
            self.assertEqual(db.client.count("knowledge", exact=True).count, 3)

    def test_failed_embedding_allows_retry_without_creating_database(self):
        self.write()
        self.urlopen.side_effect = ConnectionError("模型服务不可用")
        with self.assertRaises(ConnectionError):
            self.build()
        self.assertFalse(self.db_path.exists())
        self.urlopen.side_effect = lambda *args, **kwargs: embedding_response()
        self.assertEqual(self.build(), 1)
        self.assertEqual(self.build(), 0)
        self.assertEqual(self.urlopen.call_count, 2)

    def test_identical_bytes_with_different_parsers_are_both_processed(self):
        self.write("notes.md", "# 标题\n正文。")
        self.write("notes.txt", "# 标题\n正文。")
        self.assertEqual(self.build(), 2)
        self.assertEqual(self.build(), 0)
        self.assertEqual(self.urlopen.call_count, 2)

    def test_changed_chunk_size_reprocesses_file(self):
        self.write(text="长正文内容。" * 20)
        self.assertEqual(self.build(), 1)
        self.assertGreater(self.build(chunk_size=20), 1)
        with patch.object(Chunker, "chunk", side_effect=AssertionError("不应重复切分")):
            self.assertEqual(self.build(chunk_size=20), 0)

    def test_changed_model_requires_new_collection_even_when_dimensions_match(self):
        self.write()
        self.assertEqual(self.build(), 1)
        with patch("rag_mcp.embed.ollama.MODEL", "other-model:v1"):
            with self.assertRaisesRegex(ValueError, "请使用新集合"):
                self.build()
            self.assertEqual(self.build(collection_name="other-model"), 1)
        self.assertEqual(self.urlopen.call_count, 2)

    def test_partial_write_is_retried_then_skipped_when_complete(self):
        file = self.write("long.txt", "一段正文。" * 1000)
        chunks = Chunker().chunk(file)
        self.assertGreater(len(chunks), 1)
        selection = Fliter().filter([file])
        embeds = [
            Embed([1.0, 0.0, 0.0], EmbedMetadata(**vars(chunk.metadata), text=chunk.text))
            for chunk in chunks
        ]
        with VectorDatabase(self.db_path) as db:
            db.create_collection("knowledge", 3)
            ids = db.upsert("knowledge", embeds, processing_keys=selection.processing_keys)
            db.client.delete("knowledge", points_selector=ids[1:])
        self.assertEqual(self.build(), len(chunks))
        with patch.object(Chunker, "chunk", side_effect=AssertionError("不应重复切分")):
            self.assertEqual(self.build(), 0)
        with VectorDatabase(self.db_path) as db:
            self.assertEqual(db.client.count("knowledge").count, 1 + len(chunks))

    @patch("rag_mcp.build_kb.build_kb")
    def test_cli_passes_multiple_paths_and_storage_options(self, build):
        with patch("sys.argv", ["rag-build-kb", "./one", "./two", "--db-path", "./db",
                                "--collection", "docs", "--chunk-size", "100"]):
            main()
        build.assert_called_once_with(["./one", "./two"], db_path="./db", collection_name="docs", chunk_size=100)


if __name__ == "__main__":
    unittest.main()
