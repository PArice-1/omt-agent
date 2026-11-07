import copy
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from qdrant_client import models

from rag_mcp.embed import Embed, EmbedMetadata
from rag_mcp.vector_databbase import VectorDatabase


def make_embed(text: str = "正文。\n", vector: list[float] | None = None) -> Embed:
    return Embed(
        vector=[1.0, 0.0, 0.0] if vector is None else vector,
        metadata=EmbedMetadata(
            source="/knowledge-base/guide.md",
            heading_path=["指南", "安装"],
            start_line=2,
            end_line=3,
            start_index=11,
            end_index=11 + len(text),
            text=text,
        ),
    )


class VectorDatabaseTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db_path = Path(directory.name) / "qdrant"
        self.db = VectorDatabase(db_path=self.db_path)
        self.addCleanup(self.db.close)

    def test_create_collection_is_empty_with_requested_dimension_and_cosine(self):
        self.assertTrue(self.db.create_collection("knowledge", vector_size=3))
        info = self.db.client.get_collection("knowledge")
        self.assertEqual(info.config.params.vectors.size, 3)
        self.assertEqual(info.config.params.vectors.distance, models.Distance.COSINE)
        self.assertEqual(self.db.client.count("knowledge").count, 0)

    def test_collection_model_is_persisted_and_mismatch_is_rejected(self):
        self.db.create_collection("knowledge", vector_size=3, embedding_model="model:v1")
        self.assertEqual(
            self.db.client.get_collection("knowledge").config.metadata,
            {"embedding_model": "model:v1"},
        )
        self.db.check_embedding_model("knowledge", "model:v1")
        with self.assertRaisesRegex(ValueError, "请使用新集合"):
            self.db.check_embedding_model("knowledge", "model:v2")

    def test_legacy_collection_without_model_metadata_is_not_rejected(self):
        self.db.create_collection("knowledge", vector_size=3)
        self.db.check_embedding_model("knowledge", "model:v1")

    def test_batch_write_preserves_all_metadata_and_can_be_searched(self):
        self.db.create_collection("knowledge", vector_size=3)
        embeds = [make_embed(), make_embed("其他片段。", [0.0, 0.0, 1.0])]
        original = copy.deepcopy(embeds)
        ids = self.db.upsert("knowledge", embeds)

        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)
        for point_id, embed in zip(ids, embeds):
            self.assertEqual(UUID(point_id).version, 4)
            point = self.db.client.retrieve(
                "knowledge", ids=[point_id], with_vectors=True, with_payload=True
            )[0]
            self.assertEqual(point.vector, embed.vector)
            self.assertEqual(point.payload, asdict(embed.metadata))
        self.assertEqual(embeds, original)

        result = self.db.client.query_points(
            "knowledge", query=[1.0, 0.0, 0.0], limit=1, with_payload=True
        ).points[0]
        self.assertEqual(result.id, ids[0])
        self.assertEqual(result.payload["text"], embeds[0].metadata.text)

    def test_repeated_content_gets_new_ids_in_same_batch_and_later_calls(self):
        self.db.create_collection("knowledge", vector_size=3)
        embed = make_embed()
        ids = self.db.upsert("knowledge", [embed, embed])
        ids.extend(self.db.upsert("knowledge", [embed]))
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(self.db.client.count("knowledge").count, 3)

    def test_optional_processing_key_persists_with_completion_metadata(self):
        self.db.create_collection("knowledge", vector_size=3)
        embed = make_embed()
        ids = self.db.upsert(
            "knowledge", [embed], processing_keys={embed.metadata.source: "sha256:file-v1:test"}
        )
        self.db.close()
        with VectorDatabase(self.db_path) as db:
            point = db.client.retrieve("knowledge", ids=ids, with_payload=True)[0]
            self.assertEqual(
                point.payload,
                asdict(embed.metadata) | {
                    "processing_key": "sha256:file-v1:test",
                    "ingestion_id": point.payload["ingestion_id"],
                    "chunk_index": 0,
                    "chunk_count": 1,
                },
            )
            self.assertEqual(UUID(point.payload["ingestion_id"]).version, 4)

    def test_chunk_indices_and_counts_are_per_file_even_when_interleaved(self):
        self.db.create_collection("knowledge", vector_size=3)
        first, second = make_embed(), make_embed("另一份文档")
        second = replace(second, metadata=replace(second.metadata, source="/other.txt"))
        embeds = [first, second, make_embed("下一片")]
        keys = {first.metadata.source: "sha256:file-v1:a", second.metadata.source: "sha256:file-v1:b"}
        ids = self.db.upsert("knowledge", embeds, processing_keys=keys)
        points = self.db.client.retrieve("knowledge", ids=ids, with_payload=True)
        by_id = {point.id: point.payload for point in points}
        payloads = [by_id[point_id] for point_id in ids]
        self.assertEqual([p["chunk_index"] for p in payloads], [0, 0, 1])
        self.assertEqual([p["chunk_count"] for p in payloads], [2, 1, 2])
        self.assertEqual(len({p["ingestion_id"] for p in payloads}), 1)
        next_ids = self.db.upsert("knowledge", [first], processing_keys=keys)
        next_point = self.db.client.retrieve("knowledge", ids=next_ids, with_payload=True)[0]
        self.assertNotEqual(next_point.payload["ingestion_id"], payloads[0]["ingestion_id"])

    def test_missing_processing_key_does_not_write_partial_batch(self):
        self.db.create_collection("knowledge", vector_size=3)
        first, second = make_embed(), make_embed("第二份")
        second = replace(second, metadata=replace(second.metadata, source="/other.txt"))
        with self.assertRaises(KeyError):
            self.db.upsert(
                "knowledge", [first, second],
                processing_keys={first.metadata.source: "sha256:file-v1:a"},
            )
        self.assertEqual(self.db.client.count("knowledge").count, 0)

    def test_invalid_processing_key_does_not_write_partial_batch(self):
        self.db.create_collection("knowledge", vector_size=3)
        for key in (None, 123, "sha256:document-v1:legacy"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.db.upsert(
                    "knowledge", [make_embed()],
                    processing_keys={make_embed().metadata.source: key},
                )
        self.assertEqual(self.db.client.count("knowledge").count, 0)

    def test_empty_input_does_not_require_a_collection(self):
        self.assertEqual(self.db.upsert("missing", []), [])
        self.assertFalse(self.db.client.collection_exists("missing"))

    def test_invalid_input_types_do_not_write_a_partial_batch(self):
        self.db.create_collection("knowledge", vector_size=3)
        embed = make_embed()
        for value in (None, embed, (embed,), [embed, "正文"]):
            with self.subTest(value=value), self.assertRaises(TypeError):
                self.db.upsert("knowledge", value)
        self.assertEqual(self.db.client.count("knowledge").count, 0)

    def test_existing_collection_is_not_cleared(self):
        self.db.create_collection("knowledge", vector_size=3)
        self.db.upsert("knowledge", [make_embed()])
        with self.assertRaises(ValueError):
            self.db.create_collection("knowledge", vector_size=3)
        self.assertEqual(self.db.client.count("knowledge").count, 1)

    def test_missing_collection_error_propagates(self):
        with self.assertRaises(ValueError):
            self.db.upsert("missing", [make_embed()])

    def test_context_manager_releases_lock_and_preserves_written_points(self):
        embed = make_embed()
        with self.db as db:
            self.assertIs(db, self.db)
            db.create_collection("knowledge", vector_size=3)
            ids = db.upsert("knowledge", [embed])

        with VectorDatabase(self.db_path) as reopened:
            points = reopened.client.retrieve("knowledge", ids=ids, with_payload=True)
            self.assertEqual(points[0].payload, asdict(embed.metadata))

    def test_context_manager_releases_lock_when_exception_propagates(self):
        error = RuntimeError("上下文中的操作失败")
        with self.assertRaises(RuntimeError) as caught, self.db as db:
            db.create_collection("knowledge", vector_size=3)
            db.upsert("knowledge", [make_embed()])
            raise error

        self.assertIs(caught.exception, error)
        with VectorDatabase(self.db_path) as reopened:
            self.assertEqual(reopened.client.count("knowledge").count, 1)

    def test_points_persist_after_client_is_closed_and_reopened(self):
        self.db.create_collection("knowledge", vector_size=3)
        embed = make_embed()
        ids = self.db.upsert("knowledge", [embed])
        self.db.close()

        reopened = VectorDatabase(db_path=str(self.db_path))
        self.addCleanup(reopened.close)
        points = reopened.client.retrieve("knowledge", ids=ids, with_payload=True)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].payload, asdict(embed.metadata))


if __name__ == "__main__":
    unittest.main()
