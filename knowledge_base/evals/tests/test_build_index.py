import hashlib
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from evals.build_index import DEFAULT_COLLECTION, build_index, main
from rag_mcp.embed import ollama
from rag_mcp.mcp import KnowledgeBase
from rag_mcp.vector_databbase import VectorDatabase


class BuildIndexTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir()
        self.db_path = self.data_dir / "storage"
        self.text = "第一行\r\n第二行\r第三行\n"
        self.write_corpus([10, 20, 30], [self.text, self.text, "<br>资料三。"])
        pq.write_table(pa.table({"id": ["q1"], "text": ["测试问题"]}), self.data_dir / "queries-test.parquet")
        pq.write_table(pa.table({"qid": ["q1"], "pid": ["10"], "score": [1]}), self.data_dir / "dev-test.parquet")
        self.addCleanup(patch.stopall)
        self.embed = patch("rag_mcp.embed.embeder.embed_text", return_value=[1.0, 0.0, 0.0]).start()

    def write_corpus(self, ids, texts):
        table = pa.table({"id": pa.array(ids, type=pa.int64()), "text": pa.array(texts, type=pa.string())})
        pq.write_table(table, self.data_dir / "corpus-test.parquet")

    def build(self, **kwargs):
        with redirect_stdout(io.StringIO()):
            return build_index(self.data_dir, **kwargs)

    def metadata(self, db: VectorDatabase) -> dict[str, Any]:
        metadata = db.client.get_collection(DEFAULT_COLLECTION).config.metadata
        assert metadata is not None
        return metadata

    def payloads(self, db: VectorDatabase, collection: str = DEFAULT_COLLECTION) -> list[dict[str, Any]]:
        points, _ = db.client.scroll(collection, limit=10, with_payload=True)
        result = []
        for point in points:
            assert point.payload is not None
            result.append(point.payload)
        return result

    def test_builds_persistent_index_without_content_filtering_or_query_embedding(self):
        with (
            patch("rag_mcp.fliter.Fliter.filter", side_effect=AssertionError("不应内容去重")),
            patch("evals.datasets.T2Retrieval.iter_queries", side_effect=AssertionError("问题不入库")),
            patch("evals.datasets.T2Retrieval.iter_qrels", side_effect=AssertionError("标注不入库")),
        ):
            self.assertEqual(self.build(batch_size=2), 3)
        self.assertEqual([call.kwargs["text"] for call in self.embed.call_args_list], [self.text, self.text, "<br>资料三。"])
        self.assertTrue(self.db_path.exists())
        with VectorDatabase(self.db_path) as db:
            payloads = {payload["source"]: payload for payload in self.payloads(db)}
            self.assertEqual(set(payloads), {"10", "20", "30"})
            payload = payloads["10"]
            self.assertEqual(payload["text"], self.text)
            self.assertEqual(payload["heading_path"], [])
            self.assertEqual((payload["start_line"], payload["end_line"]), (0, 3))
            self.assertEqual((payload["start_index"], payload["end_index"]), (0, len(self.text)))
            metadata = self.metadata(db)
            self.assertTrue(metadata["build_complete"])
            self.assertEqual(metadata["embedding_model"], ollama.MODEL)
            self.assertEqual(metadata["document_count"], 3)
            self.assertEqual(metadata["chunk_count"], 3)
            self.assertEqual(metadata["chunk_size"], 1024)
            self.assertEqual(metadata["indexing"], "chunked_documents_v1")
            expected_hash = hashlib.sha256((self.data_dir / "corpus-test.parquet").read_bytes()).hexdigest()
            self.assertEqual(metadata["corpus_sha256"], expected_hash)

    def test_line_ranges_follow_cr_lf_boundaries_without_changing_text(self):
        for index, (text, lines) in enumerate((
            ("正文", 1), ("正文\n", 1), ("正文\r\n\r\n", 2), ("正文\u2028仍在同一行", 1),
        )):
            with self.subTest(text=text):
                self.write_corpus([10], [text])
                name = f"line-test-{index}"
                self.build(collection_name=name)
                with VectorDatabase(self.db_path) as db:
                    payload = self.payloads(db, name)[0]
                    self.assertEqual(payload["end_line"], lines)
                    self.assertEqual(payload["text"], text)

    def test_search_returns_original_document_ids_in_source(self):
        self.build()
        with patch("rag_mcp.embed.ollama.embed_text", return_value=[1.0, 0.0, 0.0]):
            results = KnowledgeBase(self.db_path, DEFAULT_COLLECTION).search("测试问题", limit=5)
        self.assertEqual({item["source"] for item in results}, {"10", "20", "30"})
        self.assertTrue(all(item["id"] != item["source"] for item in results))

    def test_existing_collection_is_rejected_before_model_requests(self):
        self.build()
        self.embed.reset_mock()
        with self.assertRaisesRegex(ValueError, "已存在"):
            self.build()
        self.embed.assert_not_called()
        with VectorDatabase(self.db_path) as db:
            self.assertEqual(db.client.count(DEFAULT_COLLECTION).count, 3)

    def test_other_collection_and_custom_storage_are_preserved(self):
        other_path = self.root / "other-storage"
        with VectorDatabase(other_path) as db:
            db.create_collection("existing", 3)
        self.assertEqual(self.build(db_path=other_path, collection_name="evaluation"), 3)
        with VectorDatabase(other_path) as db:
            self.assertTrue(db.client.collection_exists("existing"))
            self.assertEqual(db.client.count("evaluation").count, 3)
        self.assertFalse(self.db_path.exists())

    def test_max_documents_is_a_corpus_prefix_not_a_query_limit(self):
        self.assertEqual(self.build(max_documents=2, batch_size=1), 2)
        self.assertEqual(self.embed.call_count, 2)
        with VectorDatabase(self.db_path) as db:
            self.assertEqual({payload["source"] for payload in self.payloads(db)}, {"10", "20"})

    def test_max_documents_above_corpus_size_keeps_the_last_partial_batch(self):
        self.assertEqual(self.build(max_documents=100, batch_size=10), 3)
        self.assertEqual(self.embed.call_count, 3)

    def test_long_text_is_split_without_silent_truncation_and_counts_documents_separately(self):
        text = "长正文" * 14000
        self.write_corpus([10], [text])
        count = self.build(chunk_size=1024, batch_size=4, max_documents=1)
        self.assertGreater(count, 1)
        embedded_texts = [call.kwargs["text"] for call in self.embed.call_args_list]
        self.assertEqual(len(embedded_texts), count)
        self.assertTrue(all(len(piece) <= 1024 for piece in embedded_texts))
        self.assertEqual("".join(embedded_texts), text)
        with VectorDatabase(self.db_path) as db:
            metadata = self.metadata(db)
            self.assertEqual(metadata["document_count"], 1)
            self.assertEqual(metadata["chunk_count"], count)
            points, _ = db.client.scroll(DEFAULT_COLLECTION, limit=count)
            self.assertEqual({point.payload["source"] for point in points if point.payload}, {"10"})

    def test_empty_corpus_skips_database_and_model(self):
        self.write_corpus([], [])
        self.assertEqual(self.build(), 0)
        self.assertFalse(self.db_path.exists())
        self.embed.assert_not_called()

    def test_invalid_options_fail_before_dataset_access(self):
        with patch("evals.build_index.T2Retrieval", side_effect=AssertionError("参数无效不应读数据")):
            for options in (
                {"batch_size": 0}, {"batch_size": True}, {"batch_size": 1.5},
                {"max_documents": 0}, {"max_documents": True}, {"max_documents": 1.5},
                {"collection_name": " "}, {"collection_name": None}, {"chunk_size": 0}, {"chunk_size": True},
            ):
                with self.subTest(options=options), self.assertRaises(ValueError):
                    self.build(**options)

    def test_duplicate_document_ids_are_not_silently_indexed_twice(self):
        self.write_corpus([10, 10], ["正文一", "正文二"])
        with self.assertRaisesRegex(ValueError, "重复.*10"):
            self.build(batch_size=1)
        with VectorDatabase(self.db_path) as db:
            self.assertEqual(db.client.count(DEFAULT_COLLECTION).count, 1)
            self.assertFalse(self.metadata(db)["build_complete"])

    def test_first_embedding_failure_identifies_document_and_creates_no_collection(self):
        self.embed.side_effect = RuntimeError("模型输入超限")
        with self.assertRaisesRegex(RuntimeError, "10") as error:
            self.build()
        self.assertIn("模型输入超限", str(error.exception.__cause__))
        with VectorDatabase(self.db_path) as db:
            self.assertFalse(db.client.collection_exists(DEFAULT_COLLECTION))

    def test_later_failure_leaves_incomplete_collection_and_releases_lock(self):
        self.embed.side_effect = [[1.0, 0.0, 0.0], RuntimeError("请求失败")]
        with self.assertRaisesRegex(RuntimeError, "20"):
            self.build(batch_size=1)
        with VectorDatabase(self.db_path) as db:
            self.assertEqual(db.client.count(DEFAULT_COLLECTION).count, 1)
            self.assertFalse(self.metadata(db)["build_complete"])
        self.embed.reset_mock()
        with self.assertRaisesRegex(ValueError, "已存在"):
            self.build()
        self.embed.assert_not_called()

    def test_dimension_changes_are_rejected_without_marking_index_complete(self):
        self.embed.side_effect = [[1.0, 0.0, 0.0], [1.0, 0.0]]
        with self.assertRaisesRegex(ValueError, "维度"):
            self.build(batch_size=1)
        with VectorDatabase(self.db_path) as db:
            self.assertFalse(self.metadata(db)["build_complete"])

    def test_persisted_count_is_checked_before_marking_build_complete(self):
        with patch.object(VectorDatabase, "upsert", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "记录数"):
                self.build()
        with VectorDatabase(self.db_path) as db:
            self.assertFalse(self.metadata(db)["build_complete"])

    @patch("evals.build_index.build_index")
    def test_cli_passes_options(self, build):
        with patch("sys.argv", [
            "build_index", "--data-dir", str(self.data_dir), "--db-path", str(self.db_path),
            "--collection", "docs", "--batch-size", "2", "--max-documents", "3", "--chunk-size", "8",
        ]):
            main()
        build.assert_called_once_with(
            self.data_dir, db_path=self.db_path, collection_name="docs", batch_size=2, max_documents=3, chunk_size=8,
        )


if __name__ == "__main__":
    unittest.main()
