import unittest

from evals.datasets import Judgment, RetrievalExample, TextRecord
from evals.metrics import score_query


def make_example(judgments=None):
    if judgments is None:
        judgments = [Judgment("q1", doc_id, 1.0) for doc_id in ("d1", "d2", "d3")]
    return RetrievalExample(
        query=TextRecord("q1", "测试问题？"),
        documents=[TextRecord("d1", "资料一")],
        judgments=judgments,
    )


class ScoreQueryTests(unittest.TestCase):
    def test_hand_calculated_example(self):
        metrics = score_query(make_example(), ["other1", "d1", "other2", "d2", "other3"])
        self.assertEqual(metrics["hit_at_k"], 1.0)
        self.assertAlmostEqual(metrics["recall_at_k"], 2 / 3)
        self.assertEqual(metrics["mrr_at_k"], 0.5)

    def test_all_relevant_documents_are_found(self):
        metrics = score_query(make_example(), ["d1", "d2", "d3"])
        self.assertEqual(metrics, {"hit_at_k": 1.0, "recall_at_k": 1.0, "mrr_at_k": 1.0})

    def test_no_hits_or_empty_results_score_zero(self):
        for results in ([], ["other1", "other2"]):
            with self.subTest(results=results):
                self.assertEqual(score_query(make_example(), results), {
                    "hit_at_k": 0.0, "recall_at_k": 0.0, "mrr_at_k": 0.0,
                })

    def test_cutoff_excludes_relevant_documents_after_k(self):
        metrics = score_query(make_example(), ["other1", "other2", "d1"], k=2)
        self.assertEqual(metrics, {"hit_at_k": 0.0, "recall_at_k": 0.0, "mrr_at_k": 0.0})

    def test_hit_at_exactly_k_is_included(self):
        metrics = score_query(make_example(), ["other1", "other2", "d3"], k=3)
        self.assertEqual(metrics["hit_at_k"], 1.0)
        self.assertAlmostEqual(metrics["recall_at_k"], 1 / 3)
        self.assertAlmostEqual(metrics["mrr_at_k"], 1 / 3)

    def test_document_deduplication_happens_before_cutoff_and_preserves_order(self):
        metrics = score_query(make_example(), ["other", "other", "d1", "d1", "d2"], k=3)
        self.assertEqual(metrics["hit_at_k"], 1.0)
        self.assertAlmostEqual(metrics["recall_at_k"], 2 / 3)
        self.assertEqual(metrics["mrr_at_k"], 0.5)

    def test_duplicate_judgments_do_not_inflate_recall_denominator(self):
        example = make_example([
            Judgment("q1", "d1", 1.0), Judgment("q1", "d1", 2.0), Judgment("q1", "d2", 1.0),
        ])
        self.assertEqual(score_query(example, ["d1"])["recall_at_k"], 0.5)

    def test_only_positive_judgments_count_and_grades_are_binary(self):
        example = make_example([
            Judgment("q1", "d1", 3.0), Judgment("q1", "d2", 0.0), Judgment("q1", "d3", -1.0),
        ])
        self.assertEqual(score_query(example, ["d2", "d3", "d1"]), {
            "hit_at_k": 1.0, "recall_at_k": 1.0, "mrr_at_k": 1 / 3,
        })

    def test_no_positive_judgments_are_rejected_instead_of_dividing_by_zero(self):
        for judgments in ([], [Judgment("q1", "d1", 0.0)], [Judgment("q1", "d1", -1.0)]):
            with self.subTest(judgments=judgments), self.assertRaisesRegex(ValueError, "正相关"):
                score_query(make_example(judgments), ["d1"])

    def test_judgments_for_another_query_are_rejected(self):
        example = make_example([Judgment("q2", "d1", 1.0)])
        with self.assertRaisesRegex(ValueError, "query_id"):
            score_query(example, ["d1"])

    def test_invalid_judgment_scores_are_rejected(self):
        for score in (float("nan"), float("inf"), float("-inf"), True):
            with self.subTest(score=score), self.assertRaisesRegex(ValueError, "score"):
                score_query(make_example([Judgment("q1", "d1", score)]), ["d1"])

    def test_invalid_judgment_document_ids_are_rejected(self):
        for document_id in ("", "  ", None, 1):
            with self.subTest(document_id=document_id), self.assertRaisesRegex(ValueError, "document_id"):
                score_query(make_example([Judgment("q1", document_id, 1.0)]), ["d1"])  # pyright: ignore[reportArgumentType]

    def test_invalid_k_is_rejected(self):
        for k in (0, -1, True, 1.5, "5", None):
            with self.subTest(k=k), self.assertRaisesRegex(ValueError, "k"):
                score_query(make_example(), [], k=k)  # pyright: ignore[reportArgumentType]

    def test_results_must_be_a_list_of_nonempty_string_ids(self):
        for results in ("d1", ("d1",), None):
            with self.subTest(results=results), self.assertRaises(TypeError):
                score_query(make_example(), results)  # pyright: ignore[reportArgumentType]
        for results in ([1], [None], [""], ["  "]):
            with self.subTest(results=results), self.assertRaises(ValueError):
                score_query(make_example(), results)  # pyright: ignore[reportArgumentType]

    def test_inputs_are_not_modified(self):
        example = make_example()
        judgments = list(example.judgments)
        documents = list(example.documents)
        results = ["d2", "d2", "d1"]
        score_query(example, results, k=2)
        self.assertEqual(results, ["d2", "d2", "d1"])
        self.assertEqual(example.judgments, judgments)
        self.assertEqual(example.documents, documents)


if __name__ == "__main__":
    unittest.main()
