import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from evals.datasets import T2Retrieval


class T2RetrievalTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.write("corpus", {"id": [10, 20], "text": ["资料一。\n", "资料二。"]})
        self.write("queries", {"id": ["q1", "q2"], "text": ["问题一？", "问题二？"]})
        self.write("dev", {"qid": ["q1", "q2", "q2"], "pid": ["10", "20", "10"],
                           "score": [0, 2, 1]})

    def write(self, name, values):
        path = self.root / f"{name}-00000.parquet"
        pq.write_table(pa.table(values), path)
        return path

    def test_counts_are_read_from_metadata(self):
        dataset = T2Retrieval(self.root)
        self.assertEqual(dataset.counts, {"corpus": 2, "queries": 2, "qrels": 3})

    def test_corpus_ids_are_strings_and_text_is_not_cleaned(self):
        records = list(T2Retrieval(self.root).iter_corpus(batch_size=1))
        self.assertEqual([item.id for item in records], ["10", "20"])
        self.assertEqual(records[0].text, "资料一。\n")

    def test_all_judgments_are_preserved_including_multiple_documents_and_zero(self):
        judgments = list(T2Retrieval(self.root).iter_qrels(batch_size=1))
        self.assertEqual([item.score for item in judgments], [0.0, 2.0, 1.0])
        self.assertEqual([item.document_id for item in judgments if item.query_id == "q2"], ["20", "10"])

    def test_first_example_joins_by_ids_and_skips_nonpositive_labels(self):
        example = T2Retrieval(self.root).first_example(batch_size=1)
        self.assertEqual(example.query.id, "q2")
        self.assertEqual(example.query.text, "问题二？")
        self.assertEqual([item.id for item in example.documents], ["20", "10"])
        self.assertEqual([item.text for item in example.documents], ["资料二。", "资料一。\n"])
        self.assertEqual([item.score for item in example.judgments], [2.0, 1.0])

    def test_examples_group_nonconsecutive_judgments_by_query(self):
        self.write("dev", {"qid": ["q2", "q1", "q2", "q1"],
                           "pid": ["20", "10", "10", "20"], "score": [2, 1, 1, 0]})
        examples = list(T2Retrieval(self.root).iter_examples(batch_size=1))
        self.assertEqual([item.query.id for item in examples], ["q2", "q1"])
        self.assertEqual([[doc.id for doc in item.documents] for item in examples], [["20", "10"], ["10"]])
        self.assertEqual([len(item.judgments) for item in examples], [2, 1])
        for example in examples:
            self.assertTrue(all(item.query_id == example.query.id for item in example.judgments))
            self.assertTrue(all(item.score > 0 for item in example.judgments))

    def test_limit_counts_queries_and_keeps_all_their_judgments(self):
        self.write("dev", {"qid": ["q2", "q1", "q2"], "pid": ["20", "10", "10"], "score": [1, 1, 1]})
        examples = list(T2Retrieval(self.root).iter_examples(limit=1, batch_size=1))
        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0].query.id, "q2")
        self.assertEqual([item.document_id for item in examples[0].judgments], ["20", "10"])

    def test_returns_lazy_iterator_and_scans_each_file_once(self):
        self.write("dev", {"qid": ["q2", "q1"], "pid": ["20", "10"], "score": [1, 1]})
        dataset = T2Retrieval(self.root)
        with (
            patch.object(dataset, "iter_qrels", wraps=dataset.iter_qrels) as qrels,
            patch.object(dataset, "iter_queries", wraps=dataset.iter_queries) as queries,
            patch.object(dataset, "iter_corpus", wraps=dataset.iter_corpus) as corpus,
        ):
            examples = dataset.iter_examples()
            self.assertIs(iter(examples), examples)
            qrels.assert_not_called()
            queries.assert_not_called()
            corpus.assert_not_called()
            self.assertEqual(len(list(examples)), 2)
            qrels.assert_called_once()
            queries.assert_called_once()
            corpus.assert_called_once()

    def test_documents_are_unique_but_raw_positive_judgments_are_preserved(self):
        self.write("dev", {"qid": ["q2", "q2"], "pid": ["20", "20"], "score": [2, 1]})
        example = next(T2Retrieval(self.root).iter_examples())
        self.assertEqual([item.id for item in example.documents], ["20"])
        self.assertEqual([item.score for item in example.judgments], [2.0, 1.0])

    def test_invalid_limits_are_rejected(self):
        dataset = T2Retrieval(self.root)
        for limit in (0, -1, True, 1.5):
            with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, "limit"):
                list(dataset.iter_examples(limit=limit))  # pyright: ignore[reportArgumentType]

    def test_limit_does_not_load_unselected_documents(self):
        self.write("dev", {"qid": ["q2", "missing"], "pid": ["20", "missing"], "score": [1, 1]})
        example = next(T2Retrieval(self.root).iter_examples(limit=1))
        self.assertEqual(example.query.id, "q2")
        self.assertEqual([item.id for item in example.documents], ["20"])

    def test_selected_duplicate_ids_are_rejected(self):
        for name, values in (
            ("corpus", {"id": [20, 20], "text": ["正文一", "正文二"]}),
            ("queries", {"id": ["q2", "q2"], "text": ["问题一", "问题二"]}),
        ):
            with self.subTest(name=name):
                path = self.root / f"{name}-00000.parquet"
                original = path.read_bytes()
                self.write(name, values)
                try:
                    with self.assertRaisesRegex(ValueError, "重复 ID"):
                        list(T2Retrieval(self.root).iter_examples())
                finally:
                    path.write_bytes(original)

    def test_no_positive_labels_produce_empty_iterator(self):
        self.write("dev", {"qid": ["q1"], "pid": ["10"], "score": [0]})
        self.assertEqual(list(T2Retrieval(self.root).iter_examples()), [])

    def test_missing_file_is_reported(self):
        (self.root / "dev-00000.parquet").unlink()
        with self.assertRaisesRegex(FileNotFoundError, "dev-"):
            T2Retrieval(self.root)

    def test_multiple_matching_versions_are_rejected(self):
        shutil.copyfile(self.root / "queries-00000.parquet", self.root / "queries-copy.parquet")
        with self.assertRaisesRegex(ValueError, "匹配到 2 个文件"):
            T2Retrieval(self.root)

    def test_missing_columns_are_reported(self):
        self.write("dev", {"qid": ["q1"], "pid": ["10"]})
        with self.assertRaisesRegex(ValueError, "score"):
            T2Retrieval(self.root)

    def test_identical_corpus_and_queries_are_rejected(self):
        shutil.copyfile(self.root / "corpus-00000.parquet", self.root / "queries-00000.parquet")
        with self.assertRaisesRegex(ValueError, "内容完全相同"):
            T2Retrieval(self.root)

    def test_blank_text_and_invalid_ids_are_rejected_during_reading(self):
        for values in (
            {"id": [None], "text": ["正文"]},
            {"id": [True], "text": ["正文"]},
            {"id": [""], "text": ["正文"]},
            {"id": [1], "text": [None]},
            {"id": [1], "text": ["  "]},
        ):
            with self.subTest(values=values):
                self.write("corpus", values)
                with self.assertRaises(ValueError):
                    list(T2Retrieval(self.root).iter_corpus())

    def test_invalid_scores_are_rejected(self):
        for score in (None, True, float("nan"), float("inf"), "not-a-score"):
            with self.subTest(score=score):
                self.write("dev", {"qid": ["q1"], "pid": ["10"], "score": [score]})
                with self.assertRaisesRegex(ValueError, "score"):
                    list(T2Retrieval(self.root).iter_qrels())

    def test_invalid_batch_sizes_are_rejected(self):
        dataset = T2Retrieval(self.root)
        for size in (0, -1, True, 1.5):
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "batch_size"):
                list(dataset.iter_queries(batch_size=size))  # pyright: ignore[reportArgumentType]

    def test_missing_referenced_ids_are_reported(self):
        for qid, pid, expected in (("missing", "10", "qid=missing"),
                                   ("q1", "missing", "pid=missing")):
            with self.subTest(qid=qid, pid=pid):
                self.write("dev", {"qid": [qid], "pid": [pid], "score": [1]})
                with self.assertRaisesRegex(ValueError, expected):
                    T2Retrieval(self.root).first_example()

    def test_no_positive_judgments_are_reported(self):
        self.write("dev", {"qid": ["q1"], "pid": ["10"], "score": [-1]})
        with self.assertRaisesRegex(ValueError, "没有 score > 0"):
            T2Retrieval(self.root).first_example()


if __name__ == "__main__":
    unittest.main()
