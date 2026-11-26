"""BM25 检索能力测试：真实分词与公式、快照对照流程及文件导出，不请求模型。"""

import hashlib
import io
import json
import math
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import Mock, patch

from qdrant_client import models

from evals.bm25 import BM25Index, SearchChunk
from evals.run_bm25 import main, run_bm25_evaluation
from rag_mcp.vector_databbase import VectorDatabase


class BM25IndexTests(unittest.TestCase):
    """通过检索结果验证公式、中文匹配、平分及无匹配边界。"""

    def test_scores_follow_positive_idf_and_saturating_term_frequency(self):
        index = BM25Index([
            SearchChunk("a", "one", "apple apple"),
            SearchChunk("b", "two", "apple pear"),
            SearchChunk("c", "three", "pear pear"),
        ], k1=1.2, b=0)
        hits = index.search("apple", limit=3)
        idf = math.log1p((3 - 2 + 0.5) / (2 + 0.5))
        self.assertEqual([hit["source"] for hit in hits], ["one", "two"])
        self.assertAlmostEqual(hits[0]["score"], idf * 2 * 2.2 / (2 + 1.2))
        self.assertAlmostEqual(hits[1]["score"], idf)
        self.assertEqual(hits, index.search("APPLE apple", limit=3))

    def test_length_normalization_prefers_shorter_text_at_equal_term_frequency(self):
        chunks = [SearchChunk("a", "long", "apple pear pear pear"), SearchChunk("b", "short", "apple")]
        self.assertEqual(BM25Index(chunks, b=0).search("apple")[0]["source"], "long")
        self.assertEqual(BM25Index(chunks, b=1).search("apple")[0]["source"], "short")

    def test_chinese_segmentation_and_empty_or_unmatched_queries(self):
        index = BM25Index([
            SearchChunk("a", "db", "向量数据库支持持久化存储"),
            SearchChunk("b", "fruit", "香蕉是一种水果"),
            SearchChunk("c", "symbols", "！！！"),
        ])
        self.assertEqual(index.search("如何持久化存储")[0]["source"], "db")
        for query in ("", " \n", "？！", "xyznotfound"):
            with self.subTest(query=query):
                self.assertEqual(index.search(query), [])
        self.assertEqual(BM25Index([SearchChunk("a", "symbols", "！！！")]).search("apple"), [])

    def test_ties_and_budget_are_deterministic_independent_of_input_order(self):
        chunks = [SearchChunk("b", "two", "apple"), SearchChunk("a", "one", "apple")]
        self.assertEqual(BM25Index(chunks).search("apple", limit=1)[0]["id"], "a")
        self.assertEqual(BM25Index(chunks).search("apple"), BM25Index(reversed(chunks)).search("apple"))

    def test_invalid_parameters_and_duplicate_chunk_ids_are_rejected(self):
        chunks = [SearchChunk("a", "one", "apple")]
        for options in ({"k1": 0}, {"k1": True}, {"k1": float("inf")}, {"k1": float("nan")},
                        {"b": -0.1}, {"b": 1.1}, {"b": False}, {"b": float("nan")}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                BM25Index(chunks, **options)
        with self.assertRaisesRegex(ValueError, "重复"):
            BM25Index(chunks * 2)
        with self.assertRaises(ValueError):
            BM25Index([])
        for limit in (0, -1, True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                BM25Index(chunks).search("apple", limit=limit)


class BM25EvaluationTests(unittest.TestCase):
    """用测试创建的真实 Qdrant 和向量排名验证完整导出，不依赖原始下载数据。"""

    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        # unittest 在 setUp 中创建真实资源；这里只声明每个实例独立的夹具状态。
        self.root = Path()
        self.storage = Path()
        self.baseline_path = Path()
        self.output = Path()
        self.metadata: dict[str, Any] = {}
        self.chunks: list[tuple[int, str, str]] = []
        self.baseline: dict[str, Any] = {}

    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.storage = self.root / "storage"
        self.baseline_path = self.root / "vector.json"
        self.output = self.root / "reports" / "bm25.json"
        self.metadata = {
            "embedding_model": "test-embedding", "dataset": "t2retrieval", "build_complete": True,
            "indexing": "chunked_documents_v1", "document_count": 4, "chunk_count": 5,
            "corpus_sha256": "test-corpus-hash", "chunk_size": 1024,
        }
        self.chunks = [
            (1, "d1", "苹果 苹果"), (2, "d1", "苹果 苹果"),
            (3, "d2", "香蕉 香蕉"), (4, "d3", "苹果 香蕉"),
            (5, "d4", "向量数据库支持持久化存储"),
        ]
        with VectorDatabase(self.storage) as db:
            db.create_collection("test", 2)
            db.client.update_collection("test", metadata=self.metadata)
            db.client.upsert("test", [
                models.PointStruct(id=chunk_id, vector=[1.0, 0.0], payload={"source": source, "text": text})
                for chunk_id, source, text in self.chunks
            ])
        self.baseline = {
            "created_at": "2026-01-01T00:00:00+00:00", "status": "completed",
            "config": {
                "collection": "test", "embedding_model": "test-embedding", "k": 2, "fetch_k": 2,
                "candidate_documents": 4, "candidate_chunks": 5, "collection_metadata": self.metadata,
                "ranking_policy": "bounded_chunk_search;first_source_occurrence;document_top_k",
                "selection_policy": "all_positive_documents_in_candidates;first_seen_positive_qid_order",
                "scope": "local_retrieval_evaluation_not_official_benchmark",
            },
            "selection": {"evaluated_queries": 3},
            "results": [
                self.result("q1", "苹果", ["d1"], [(3, "d2"), (1, "d1")]),
                self.result("q2", "香蕉", ["d2", "d3", "d2"], [(3, "d2"), (1, "d1")]),
                self.result("q3", "xyznotfound", ["d4"], [(5, "d4"), (4, "d3")]),
            ],
        }
        self.save_baseline()
        # 任一真实模型调用都应使本测试失败；BM25 不使用 embedding。
        self.addCleanup(patch.stopall)
        patch("rag_mcp.embed.ollama.embed_text", side_effect=AssertionError("BM25 不应请求模型")).start()

    @staticmethod
    def result(query_id: str, query: str, expected: list[str], hits: list[tuple[int, str]]) -> dict[str, Any]:
        return {
            "query_id": query_id, "query": query, "expected_document_ids": expected,
            "retrieved_document_ids": list(dict.fromkeys(source for _, source in hits)),
            "retrieved_chunks": [{"chunk_id": str(chunk_id), "document_id": source} for chunk_id, source in hits],
        }

    def save_baseline(self):
        self.baseline_path.write_text(json.dumps(self.baseline, ensure_ascii=False), encoding="utf-8")

    def run_eval(self, **options: Any) -> dict[str, Any]:
        args: dict[str, Any] = {"db_path": self.storage, "output": self.output}
        args.update(options)
        with redirect_stdout(io.StringIO()):
            return run_bm25_evaluation(self.baseline_path, **args)

    def hashes(self):
        return {str(path.relative_to(self.storage)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.storage.rglob("*") if path.is_file()}

    def test_runs_real_bm25_exports_comparison_and_preserves_source_database(self):
        original = self.hashes()
        baseline_bytes = self.baseline_path.read_bytes()
        report = self.run_eval()
        self.assertEqual(self.hashes(), original)
        self.assertEqual(self.baseline_path.read_bytes(), baseline_bytes)
        self.assertEqual([item["query_id"] for item in report["results"]], ["q1", "q2", "q3"])
        first, second, unmatched = report["results"]
        self.assertEqual(first["retrieved_document_ids"], ["d1"])
        self.assertEqual(len(first["retrieved_chunks"]), 2)
        self.assertTrue(first["fewer_than_k_documents"])
        self.assertEqual(second["retrieved_document_ids"], ["d2", "d3"])
        self.assertEqual(second["metrics"]["recall_at_k"], 1.0)
        self.assertEqual(unmatched["retrieved_document_ids"], [])
        self.assertEqual(unmatched["metrics"], dict.fromkeys(("hit_at_k", "recall_at_k", "mrr_at_k"), 0.0))
        self.assertAlmostEqual(report["summary"]["hit_at_k"], 2 / 3)
        self.assertAlmostEqual(report["summary"]["recall_at_k"], 2 / 3)
        self.assertAlmostEqual(report["vector_summary"]["mrr_at_k"], 5 / 6)
        self.assertAlmostEqual(report["delta"]["hit_at_k"], -1 / 3)
        self.assertEqual(report["config"]["fetch_k"], 2)
        self.assertEqual(len(report["config"]["candidate_payload_sha256"]), 64)
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), report)
        markdown = self.output.with_suffix(".md").read_text(encoding="utf-8")
        for text in ("BM25 与向量检索", "历史报告", "不是完整 T2Retrieval", "0.666667", "k1=1.2"):
            self.assertIn(text, markdown)
        self.assertEqual(report["vector_baseline"]["sha256"], hashlib.sha256(baseline_bytes).hexdigest())

    def test_empty_baseline_writes_null_metrics(self):
        self.baseline.update(status="no_eligible_queries", results=[], selection={"evaluated_queries": 0})
        self.save_baseline()
        report = self.run_eval()
        self.assertEqual(report["summary"], dict.fromkeys(("hit_at_k", "recall_at_k", "mrr_at_k")))
        self.assertEqual(report["delta"], report["summary"])
        self.assertIn("未执行检索", self.output.with_suffix(".md").read_text(encoding="utf-8"))

    def test_existing_json_or_markdown_is_never_overwritten(self):
        self.output.parent.mkdir()
        for path in (self.output, self.output.with_suffix(".md")):
            with self.subTest(path=path):
                path.write_text("原报告", encoding="utf-8")
                with self.assertRaises(FileExistsError):
                    self.run_eval()
                self.assertEqual(path.read_text(encoding="utf-8"), "原报告")
                path.unlink()

    def test_missing_database_is_not_created(self):
        missing = self.root / "missing"
        with self.assertRaises(FileNotFoundError):
            self.run_eval(db_path=missing)
        self.assertFalse(missing.exists())
        self.assertFalse(self.output.exists())

    def test_changed_metadata_or_candidate_count_is_rejected(self):
        with VectorDatabase(self.storage) as db:
            db.client.update_collection("test", metadata={**self.metadata, "build_complete": False})
        with self.assertRaisesRegex(ValueError, "未构建完成"):
            self.run_eval()
        with VectorDatabase(self.storage) as db:
            db.client.update_collection("test", metadata={**self.metadata, "corpus_sha256": "changed"})
        with self.assertRaisesRegex(ValueError, "元数据"):
            self.run_eval()
        with VectorDatabase(self.storage) as db:
            db.client.update_collection("test", metadata=self.metadata)
            db.client.delete("test", models.PointIdsList(points=[5]))
        with self.assertRaisesRegex(ValueError, "片段或文档数"):
            self.run_eval()
        self.assertFalse(self.output.exists())

    def test_incomplete_positive_coverage_and_replaced_chunk_identity_are_rejected(self):
        self.baseline["results"][0]["expected_document_ids"].append("missing")
        self.save_baseline()
        with self.assertRaisesRegex(ValueError, "完整覆盖"):
            self.run_eval()
        self.baseline["results"][0]["expected_document_ids"].pop()
        self.baseline["results"][0]["retrieved_chunks"][0]["chunk_id"] = "999"
        self.save_baseline()
        with self.assertRaisesRegex(ValueError, "当前候选库"):
            self.run_eval()
        self.assertFalse(self.output.exists())

    def test_malformed_query_or_rankings_fail_without_report(self):
        for key, value in (("query_id", ""), ("query", " "), ("expected_document_ids", []),
                           ("retrieved_document_ids", ["d1", "d2"]), ("retrieved_chunks", [])):
            original = self.baseline["results"][0][key]
            with self.subTest(key=key):
                self.baseline["results"][0][key] = value
                self.save_baseline()
                with self.assertRaises(ValueError):
                    self.run_eval()
                self.assertFalse(self.output.exists())
            self.baseline["results"][0][key] = original

    def test_query_failure_identifies_query_and_keeps_original_cause(self):
        with patch("evals.run_bm25.BM25Index.search", side_effect=RuntimeError("检索失败")):
            with self.assertRaisesRegex(RuntimeError, "q1") as error:
                self.run_eval()
        self.assertEqual(str(error.exception.__cause__), "检索失败")
        self.assertFalse(self.output.exists())

    def test_invalid_output_and_bm25_parameters_are_rejected(self):
        for options in ({"output": self.root / "bad.txt"}, {"k1": 0}, {"b": 2}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_eval(**options)
        self.assertFalse(self.output.exists())

    @patch("evals.run_bm25.run_bm25_evaluation")
    def test_cli_options(self, run: Mock):
        with patch("sys.argv", ["run_bm25", "--baseline-report", str(self.baseline_path),
                                "--db-path", str(self.storage), "--k1", "1.5", "--b", "0.5",
                                "--output", str(self.output)]):
            main()
        run.assert_called_once_with(self.baseline_path, db_path=self.storage, k1=1.5, b=0.5, output=self.output)


if __name__ == "__main__":
    unittest.main()
