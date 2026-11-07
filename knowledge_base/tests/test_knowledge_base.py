import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from rag_mcp.embed import Embed, EmbedMetadata, ollama
from rag_mcp.mcp import KnowledgeBase
from rag_mcp.vector_databbase import VectorDatabase


def make_embed(source, text, start=0, vector=None, headings=None):
    return Embed(
        [1.0, 0.0, 0.0] if vector is None else vector,
        EmbedMetadata(source, ["指南", "Python"] if headings is None else headings,
                      0, 1, start, start + len(text), text),
    )


class KnowledgeBaseTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db_path = Path(directory.name) / "db"
        self.kb = KnowledgeBase(self.db_path)
        self.first = "/docs/a.md"
        self.second = "/other/b.txt"
        self.embeds = [
            make_embed(self.first, "Install Python", start=0),
            make_embed(self.second, "Other topic", vector=[0.0, 1.0, 0.0], headings=[]),
            make_embed(self.first, "Use venv ERROR42", start=30, vector=[0.8, 0.2, 0.0]),
        ]
        self.keys = {self.first: "sha256:file-v1:a", self.second: "sha256:file-v1:b"}
        with VectorDatabase(self.db_path) as db:
            db.create_collection("knowledge", 3, embedding_model=ollama.MODEL)
            self.ids = db.upsert("knowledge", self.embeds, processing_keys=self.keys)

    @patch("rag_mcp.embed.ollama.embed_text", return_value=[1.0, 0.0, 0.0])
    def test_semantic_search_uses_persisted_vectors_once_and_keeps_source_metadata(self, embed):
        with patch("rag_mcp.chunk.Chunker.chunk", side_effect=AssertionError("不能重新切分")):
            results = self.kb.search("如何安装？")
        self.assertEqual([item["id"] for item in results], [self.ids[0], self.ids[2], self.ids[1]])
        self.assertEqual(results[0]["text"], "Install Python")
        self.assertEqual(results[0]["source"], self.first)
        self.assertEqual(results[0]["heading_path"], ["指南", "Python"])
        self.assertAlmostEqual(results[0]["score"], 1.0)
        self.assertGreater(results[1]["score"], results[2]["score"])
        self.assertTrue(all("vector" not in item and "embedding" not in item for item in results))
        embed.assert_called_once_with(
            "Instruct: Given a web search query, retrieve relevant passages "
            "that answer the query\nQuery: 如何安装？"
        )

    @patch("rag_mcp.embed.ollama.embed_text", return_value=[1.0, 0.0, 0.0])
    def test_search_limit_source_and_min_score(self, embed):
        self.assertEqual(len(self.kb.search("问题", limit=1)), 1)
        self.assertEqual([item["source"] for item in self.kb.search("问题", source=self.second)], [self.second])
        self.assertEqual([item["id"] for item in self.kb.search("问题", min_score=0.99)], [self.ids[0]])
        self.assertEqual(len(self.kb.search("问题", min_score=0)), 3)

    @patch("rag_mcp.embed.ollama.embed_text", return_value=[1.0, 0.0, 0.0])
    def test_negative_cosine_score_is_preserved_and_threshold_is_inclusive(self, embed):
        with VectorDatabase(self.db_path) as db:
            opposite = make_embed("/opposite.txt", "反向向量", vector=[-1.0, 0.0, 0.0])
            db.upsert("knowledge", [opposite])
        results = self.kb.search("问题", min_score=-1)
        self.assertEqual(results[-1]["source"], "/opposite.txt")
        self.assertAlmostEqual(results[-1]["score"], -1)
        self.assertEqual(len(self.kb.search("问题", min_score=0)), 3)

    @patch("rag_mcp.embed.ollama.embed_text")
    def test_missing_source_skips_model_request(self, embed):
        self.assertEqual(self.kb.search("问题", source="/missing.md"), [])
        embed.assert_not_called()

    @patch("rag_mcp.embed.ollama.embed_text")
    def test_other_collection_is_empty_and_is_not_created(self, embed):
        kb = KnowledgeBase(self.db_path, "other")
        self.assertEqual(kb.search("问题"), [])
        self.assertFalse(kb.stats()["exists"])
        self.assertEqual(kb.list_documents()["items"], [])
        embed.assert_not_called()
        with VectorDatabase(self.db_path) as db:
            self.assertFalse(db.client.collection_exists("other"))

    @patch("rag_mcp.embed.ollama.embed_text")
    def test_model_mismatch_fails_before_request_even_with_same_dimension(self, embed):
        with (
            patch("rag_mcp.embed.ollama.MODEL", "different-model"),
            self.assertRaisesRegex(ValueError, "请使用新集合"),
        ):
            self.kb.search("问题")
        embed.assert_not_called()

    @patch("rag_mcp.embed.ollama.embed_text", return_value=[1.0])
    def test_query_dimension_mismatch_propagates(self, embed):
        with self.assertRaises(ValueError):
            self.kb.search("问题")

    @patch("rag_mcp.embed.ollama.embed_text", side_effect=ConnectionError("模型不可用"))
    def test_query_model_error_propagates(self, embed):
        with self.assertRaisesRegex(ConnectionError, "模型不可用"):
            self.kb.search("问题")

    @patch("rag_mcp.embed.ollama.embed_text", side_effect=AssertionError("不应调用模型"))
    def test_keyword_search_matches_heading_and_body_without_model(self, embed):
        title_results = self.kb.keyword_search("pYtHoN")
        self.assertEqual({item["id"] for item in title_results["items"]}, {self.ids[0], self.ids[2]})
        self.assertEqual(self.kb.keyword_search("error42")["items"][0]["id"], self.ids[2])
        self.assertEqual(self.kb.keyword_search("ERROR42", source=self.second)["items"], [])
        self.assertEqual(self.kb.keyword_search("missing")["items"], [])

    def test_keyword_search_pagination_has_no_duplicates(self):
        first = self.kb.keyword_search("Python", limit=1)
        second = self.kb.keyword_search("Python", limit=1, offset=1)
        self.assertTrue(first["has_more"])
        self.assertFalse(second["has_more"])
        self.assertNotEqual(first["items"][0]["id"], second["items"][0]["id"])
        self.assertEqual(self.kb.keyword_search("Python", offset=2)["items"], [])

    def test_list_documents_groups_chunks_and_reports_completeness(self):
        result = self.kb.list_documents(limit=1)
        self.assertEqual(result["total"], 2)
        self.assertTrue(result["has_more"])
        first = result["items"][0]
        self.assertEqual(first["source"], self.first)
        self.assertEqual(first["stored_chunks"], 2)
        self.assertEqual(first["expected_chunks"], 2)
        self.assertTrue(first["complete"])
        second = self.kb.list_documents(limit=1, offset=1)
        self.assertEqual(second["items"][0]["source"], self.second)
        self.assertFalse(second["has_more"])

    def test_get_document_orders_by_original_position_and_paginates(self):
        result = self.kb.get_document(self.first, limit=1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["items"][0]["text"], "Install Python")
        self.assertTrue(result["has_more"])
        second = self.kb.get_document(self.first, limit=1, offset=1)
        self.assertEqual(second["items"][0]["text"], "Use venv ERROR42")
        self.assertFalse(second["has_more"])

    def test_get_document_filters_version_and_ingestion_without_reading_source_files(self):
        changed = make_embed(self.first, "新版正文")
        with VectorDatabase(self.db_path) as db:
            ids = db.upsert("knowledge", [changed], processing_keys={self.first: "sha256:file-v1:new"})
        entries = self.kb.list_documents()["items"]
        self.assertEqual(len(entries), 3)
        latest = next(item for item in entries if item["processing_key"] == "sha256:file-v1:new")
        result = self.kb.get_document(self.first, processing_key=latest["processing_key"],
                                      ingestion_id=latest["ingestion_id"])
        self.assertEqual([item["id"] for item in result["items"]], ids)
        self.assertEqual(self.kb.get_document(self.first)["total"], 3)
        self.assertEqual(self.kb.get_document("/etc/passwd")["items"], [])
        self.assertEqual(self.kb.get_document(self.first, ingestion_id="missing")["items"], [])

    def test_get_chunk_returns_public_fields_or_none(self):
        result = self.kb.get_chunk(self.ids[0])
        self.assertEqual(result["text"], "Install Python")
        self.assertEqual(result["processing_key"], self.keys[self.first])
        self.assertNotIn("vector", result)
        self.assertIsNone(self.kb.get_chunk(str(uuid4())))
        with self.assertRaises(ValueError):
            self.kb.get_chunk("not-a-point-id")
        with self.assertRaises(ValueError):
            self.kb.get_chunk(str(2**64))

    def test_stats_reports_collection_model_dimension_and_counts(self):
        result = self.kb.stats()
        self.assertTrue(result["exists"])
        self.assertEqual(result["collection_name"], "knowledge")
        self.assertEqual(result["chunk_count"], 3)
        self.assertEqual(result["source_count"], 2)
        self.assertEqual(result["document_count"], 2)
        self.assertEqual(result["complete_document_count"], 2)
        self.assertEqual(result["vector_size"], 3)
        self.assertEqual(result["embedding_model"], ollama.MODEL)

    def test_partial_write_is_reported_as_incomplete(self):
        with VectorDatabase(self.db_path) as db:
            db.client.delete("knowledge", points_selector=[self.ids[2]])
        document = self.kb.list_documents()["items"][0]
        self.assertEqual(document["stored_chunks"], 1)
        self.assertFalse(document["complete"])
        self.assertEqual(self.kb.stats()["complete_document_count"], 1)

    def test_legacy_records_are_readable_without_claiming_completeness(self):
        with VectorDatabase(self.db_path) as db:
            legacy_id = db.upsert("knowledge", [make_embed("/legacy.txt", "历史正文")])[0]
        legacy = next(item for item in self.kb.list_documents()["items"] if item["source"] == "/legacy.txt")
        self.assertIsNone(legacy["complete"])
        self.assertEqual(self.kb.get_chunk(legacy_id)["text"], "历史正文")
        self.assertEqual(self.kb.get_document("/legacy.txt")["total"], 1)

    def test_reads_more_than_one_scroll_page(self):
        source = "/large.txt"
        embeds = [make_embed(source, f"第 {index} 片", start=index * 100) for index in range(257)]
        with VectorDatabase(self.db_path) as db:
            db.upsert("knowledge", embeds, processing_keys={source: "sha256:file-v1:large"})
        self.assertEqual(self.kb.stats()["chunk_count"], 260)
        self.assertEqual(self.kb.get_document(source, offset=256)["items"][0]["text"], "第 256 片")
        self.assertTrue(self.kb.keyword_search("第", offset=256)["items"][0]["text"].startswith("第"))

    def test_invalid_inputs_fail_before_accessing_database(self):
        for action in (
            lambda: self.kb.search(" "), lambda: self.kb.search("q", limit=0),
            lambda: self.kb.search("q", limit=True), lambda: self.kb.search("q", source=""),
            lambda: self.kb.search("q", min_score=float("nan")),
            lambda: self.kb.search("q", min_score=2), lambda: self.kb.search("q", min_score=True),
            lambda: self.kb.keyword_search(""), lambda: self.kb.keyword_search("q", offset=-1),
            lambda: self.kb.list_documents(limit=101), lambda: self.kb.get_document(""),
            lambda: self.kb.get_document(self.first, offset=True),
        ):
            with (
                self.subTest(action=action),
                patch.object(self.kb, "_database", side_effect=AssertionError("不应访问数据库")),
                self.assertRaises(ValueError),
            ):
                action()

    def test_read_methods_release_database_lock(self):
        self.kb.stats()
        self.kb.list_documents()
        self.kb.get_document(self.first)
        self.kb.get_chunk(self.ids[0])
        with VectorDatabase(self.db_path) as db:
            self.assertEqual(db.client.count("knowledge").count, 3)


class EmptyKnowledgeBaseTests(unittest.TestCase):
    @patch("rag_mcp.embed.ollama.embed_text", side_effect=AssertionError("不应请求模型"))
    def test_missing_database_stays_missing(self, embed):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "not-created"
            kb = KnowledgeBase(path)
            self.assertEqual(kb.search("问题"), [])
            self.assertEqual(kb.keyword_search("关键词")["items"], [])
            self.assertEqual(kb.list_documents()["items"], [])
            self.assertEqual(kb.get_document("/notes.md")["items"], [])
            self.assertIsNone(kb.get_chunk(str(uuid4())))
            self.assertFalse(kb.stats()["exists"])
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
