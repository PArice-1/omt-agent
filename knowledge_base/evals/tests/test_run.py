import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from evals.build_index import build_index
from evals.run import main, run_evaluation
from rag_mcp.vector_databbase import VectorDatabase


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.storage = self.data / "storage"
        self.output = self.root / "results" / "report.json"
        self.collection = "evaluation"
        self.write("corpus", {"id": [10, 20, 30, 40], "text": ["资料一", "资料二", "资料三", "未入库资料"]})
        self.write("queries", {"id": ["partial", "q2", "q3", "zero"], "text": ["不完整的问题", "第二道题", "第三道题", "无正标注"]})
        self.write("dev", {"qid": ["partial", "q2", "q3", "partial", "q3", "q3", "zero"],
                           "pid": [10, 20, 10, 40, 20, 10, 30], "score": [1, 1, 1, 1, 1, 2, 0]})
        with patch("rag_mcp.embed.embeder.embed_text", side_effect=lambda text: {
            "资料一": [1.0, 0.0, 0.0], "资料二": [0.0, 1.0, 0.0], "资料三": [-1.0, 0.0, 0.0],
        }[text]), redirect_stdout(io.StringIO()):
            build_index(self.data, collection_name=self.collection, max_documents=3)

    def write(self, name, values):
        pq.write_table(pa.table(values), self.data / f"{name}-test.parquet")

    def run_eval(self, **options):
        args = {"collection_name": self.collection, "output": self.output, "k": 2}
        args.update(options)
        with redirect_stdout(io.StringIO()):
            return run_evaluation(self.data, **args)

    def update_metadata(self, **changes):
        with VectorDatabase(self.storage) as db:
            metadata = db.client.get_collection(self.collection).config.metadata or {}
            db.client.update_collection(self.collection, metadata={**metadata, **changes})

    @patch("evals.run.KnowledgeBase.search")
    def test_selects_after_full_judgments_and_writes_correct_means_and_reports(self, search):
        search.side_effect = [
            [{"source": "30", "score": 0.9}, {"source": "20", "score": 0.8}],
            [{"source": "10", "score": 0.9}, {"source": "30", "score": 0.8}],
        ]
        report = self.run_eval(batch_size=1)
        self.assertEqual([item["query_id"] for item in report["results"]], ["q2", "q3"])
        self.assertEqual(report["results"][1]["expected_document_ids"], ["10", "20"])
        self.assertEqual(report["summary"], {"hit_at_k": 1.0, "recall_at_k": 0.75, "mrr_at_k": 0.75})
        self.assertEqual(report["selection"], {
            "positive_queries": 3, "eligible_queries": 2, "excluded_incomplete_coverage": 1,
            "excluded_by_limit": 0, "evaluated_queries": 2,
        })
        self.assertEqual(json.loads(self.output.read_text()), report)
        markdown = self.output.with_suffix(".md").read_text()
        self.assertIn("不是完整 T2Retrieval", markdown)
        self.assertIn("0.750000", markdown)
        for call in search.call_args_list:
            self.assertEqual(call.kwargs, {"limit": 50})

    @patch("evals.run.KnowledgeBase.search", return_value=[])
    def test_limit_is_applied_after_coverage_filter_and_empty_search_scores_zero(self, search):
        report = self.run_eval(max_queries=1)
        self.assertEqual(report["results"][0]["query_id"], "q2")
        self.assertEqual(report["summary"], {"hit_at_k": 0.0, "recall_at_k": 0.0, "mrr_at_k": 0.0})
        self.assertEqual(report["selection"]["excluded_by_limit"], 1)
        search.assert_called_once_with("第二道题", limit=50)

    @patch("evals.run.KnowledgeBase.search")
    def test_no_eligible_queries_writes_null_metrics_without_model_calls(self, search):
        self.write("dev", {"qid": ["partial"], "pid": [40], "score": [1]})
        report = self.run_eval()
        self.assertEqual(report["status"], "no_eligible_queries")
        self.assertEqual(report["summary"], dict.fromkeys(("hit_at_k", "recall_at_k", "mrr_at_k")))
        self.assertEqual(report["results"], [])
        self.assertIn("未执行检索", self.output.with_suffix(".md").read_text())
        search.assert_not_called()

    def test_actual_knowledge_base_search_uses_original_source_ids(self):
        with patch("rag_mcp.embed.ollama.embed_text", side_effect=lambda text:
                   [0.0, 1.0, 0.0] if "第二" in text else [1.0, 0.0, 0.0]) as embed:
            report = self.run_eval()
        self.assertEqual(embed.call_count, 2)
        self.assertEqual(report["summary"], {"hit_at_k": 1.0, "recall_at_k": 1.0, "mrr_at_k": 1.0})
        self.assertEqual(report["results"][0]["retrieved_document_ids"][0], "20")

    @patch("evals.run.KnowledgeBase.search")
    def test_invalid_or_changed_index_is_rejected_before_search(self, search):
        for changes, message in (
            ({"build_complete": False}, "未构建完成"),
            ({"build_complete": True, "embedding_model": "other"}, "模型"),
            ({"embedding_model": "qwen3-embedding:0.6b", "document_count": 99}, "记录数"),
            ({"document_count": 3, "corpus_sha256": "changed"}, "SHA-256"),
        ):
            with self.subTest(changes=changes):
                self.update_metadata(**changes)
                with self.assertRaisesRegex(ValueError, message):
                    self.run_eval()
        search.assert_not_called()
        self.assertFalse(self.output.exists())

    @patch("evals.run.KnowledgeBase.search")
    def test_chunked_sources_are_deduplicated_before_document_cutoff(self, search):
        self.write("corpus", {"id": [10, 20, 30, 40], "text": ["正文一" * 100, "资料二", "资料三", "未入库"]})
        with patch("rag_mcp.embed.embeder.embed_text", return_value=[1.0, 0.0, 0.0]), redirect_stdout(io.StringIO()):
            chunks = build_index(self.data, collection_name="chunked", max_documents=3, chunk_size=16)
        search.return_value = [
            {"id": "chunk-a", "source": "10", "score": 0.9},
            {"id": "chunk-b", "source": "10", "score": 0.8},
            {"id": "chunk-c", "source": "10", "score": 0.7},
            {"id": "chunk-d", "source": "20", "score": 0.6},
        ]
        report = self.run_eval(collection_name="chunked", fetch_k=10)
        self.assertGreater(chunks, 3)
        self.assertEqual(report["config"]["candidate_documents"], 3)
        self.assertEqual(report["config"]["candidate_chunks"], chunks)
        self.assertEqual(report["config"]["fetch_k"], 10)
        result = report["results"][0]
        self.assertEqual(result["retrieved_document_ids"], ["10", "20"])
        self.assertEqual(result["retrieved"][1]["first_chunk_rank"], 4)
        self.assertEqual(len(result["retrieved_chunks"]), 4)
        self.assertEqual(result["metrics"]["mrr_at_k"], 0.5)
        self.assertFalse(result["fewer_than_k_documents"])
        self.assertEqual(report["results"][1]["metrics"]["recall_at_k"], 1.0)
        self.assertEqual(search.call_args.kwargs, {"limit": 10})

    @patch("evals.run.KnowledgeBase.search")
    def test_bounded_search_does_not_pretend_to_fill_k_unique_documents(self, search):
        search.return_value = [{"source": "10", "score": 1.0}, {"source": "10", "score": 0.9}]
        report = self.run_eval(fetch_k=2)
        result = report["results"][0]
        self.assertEqual(result["retrieved_document_ids"], ["10"])
        self.assertTrue(result["fewer_than_k_documents"])

    @patch("evals.run.KnowledgeBase.search", return_value=[])
    def test_legacy_single_vector_collection_remains_readable(self, search):
        self.update_metadata(indexing="one_record_one_vector")
        report = self.run_eval(max_queries=1)
        self.assertEqual(report["config"]["fetch_k"], 2)
        search.assert_called_once_with("第二道题", limit=2)

    @patch("evals.run.KnowledgeBase.search")
    def test_chunk_count_mismatch_is_rejected_before_search(self, search):
        self.update_metadata(chunk_count=999)
        with self.assertRaisesRegex(ValueError, "记录数"):
            self.run_eval()
        search.assert_not_called()

    @patch("evals.run.KnowledgeBase.search")
    def test_missing_storage_is_not_created(self, search):
        missing = self.root / "missing"
        with self.assertRaises(FileNotFoundError):
            self.run_eval(db_path=missing)
        self.assertFalse(missing.exists())
        search.assert_not_called()

    @patch("evals.run.KnowledgeBase.search", side_effect=RuntimeError("Ollama 失败"))
    def test_query_failure_preserves_cause_and_does_not_write_success_report(self, search):
        with self.assertRaisesRegex(RuntimeError, "q2") as error:
            self.run_eval()
        self.assertIn("Ollama 失败", str(error.exception.__cause__))
        self.assertFalse(self.output.exists())

    @patch("evals.run.KnowledgeBase.search")
    def test_existing_report_is_not_overwritten(self, search):
        self.output.parent.mkdir()
        self.output.with_suffix(".md").write_text("原报告")
        with self.assertRaises(FileExistsError):
            self.run_eval()
        self.assertEqual(self.output.with_suffix(".md").read_text(), "原报告")
        search.assert_not_called()

    def test_invalid_parameters_are_rejected(self):
        for options in ({"max_queries": 0}, {"max_queries": True}, {"k": 101}, {"k": False},
                        {"batch_size": 0}, {"fetch_k": 1}, {"fetch_k": 101}, {"fetch_k": True},
                        {"output": self.root / "report.txt"}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_eval(**options)

    @patch("evals.run.run_evaluation")
    def test_cli_options(self, run):
        with patch("sys.argv", ["run", "--data-dir", str(self.data), "--db-path", str(self.storage),
                                "--collection", "test", "--max-queries", "7", "--k", "3",
                                "--batch-size", "2", "--fetch-k", "7", "--output", str(self.output)]):
            main()
        run.assert_called_once_with(self.data, db_path=self.storage, collection_name="test",
                                    max_queries=7, k=3, batch_size=2, fetch_k=7, output=self.output)


if __name__ == "__main__":
    unittest.main()
