import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rag_mcp.embed import Embed, EmbedMetadata
from rag_mcp.fliter import (
    FileSelection,
    Fliter,
    ProcessingProfile,
    file_processing_key,
    remove_duplicates,
)
from rag_mcp.fliter.duplicate import stored_processing_keys
from rag_mcp.vector_databbase import VectorDatabase


def make_embed(file, text="正文。"):
    return Embed([1.0, 0.0, 0.0], EmbedMetadata(str(file), [], 0, 1, 0, len(text), text))


def payload(key="sha256:file-v1:test", source="/a.md", index=0, count=2, ingestion="run-1"):
    return {
        "source": source,
        "processing_key": key,
        "ingestion_id": ingestion,
        "chunk_index": index,
        "chunk_count": count,
    }


class FileFilterTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.first = self.write("a.md", "# 标题\n正文。")
        self.copy = self.write("copy.md", "# 标题\n正文。")

    def write(self, name, text):
        file = self.root / name
        file.write_text(text, encoding="utf-8")
        return file

    def test_same_batch_keeps_first_file_without_parsing_or_changing_input(self):
        files = [self.first, self.copy]
        with patch("rag_mcp.chunk.Chunker.chunk", side_effect=AssertionError("不能切分")):
            result = Fliter().filter(files)
        self.assertEqual(result.files, [self.first])
        self.assertEqual(set(result.processing_keys), {str(self.first)})
        self.assertEqual(files, [self.first, self.copy])

    def test_renamed_file_has_same_key_but_modified_bytes_do_not(self):
        profile = ProcessingProfile()
        original = file_processing_key(self.first, profile)
        self.assertEqual(file_processing_key(self.copy, profile), original)
        # 精确比较原始字节，不忽略空白。
        self.copy.write_bytes(self.copy.read_bytes() + b"\n")
        self.assertNotEqual(file_processing_key(self.copy, profile), original)

    def test_parser_type_participates_but_suffix_case_does_not(self):
        upper = self.write("upper.MD", self.first.read_text(encoding="utf-8"))
        txt = self.write("notes.txt", self.first.read_text(encoding="utf-8"))
        result = Fliter().filter([self.first, upper, txt])
        self.assertEqual(result.files, [self.first, txt])

    def test_each_processing_setting_participates_in_key(self):
        profile = ProcessingProfile()
        original = file_processing_key(self.first, profile)
        for change in (
            {"chunk_size": 100},
            {"chunk_version": "recursive-v2"},
            {"embedding_model": "other-model:v1"},
            {"embedding_version": "heading-body-v2"},
        ):
            with self.subTest(change=change):
                self.assertNotEqual(file_processing_key(self.first, replace(profile, **change)), original)

    def test_profile_rejects_invalid_chunk_sizes(self):
        for size in (True, 0, -1, 1.5):
            with self.subTest(size=size), self.assertRaises(ValueError):
                ProcessingProfile(chunk_size=size)

    def test_duplicate_rule_preserves_inputs_and_excludes_stored_files(self):
        selection = Fliter(rules=[]).filter([self.first, self.copy])
        stored = set(selection.processing_keys.values())
        original_keys = dict(selection.processing_keys)
        self.assertEqual(remove_duplicates(selection, stored), FileSelection([], {}))
        self.assertEqual(selection.files, [self.first, self.copy])
        self.assertEqual(selection.processing_keys, original_keys)
        self.assertEqual(stored, set(original_keys.values()))

    def test_rules_run_in_order_and_empty_rules_disable_deduplication(self):
        calls = []

        def first_rule(selection, stored):
            calls.append("first")
            return FileSelection(selection.files[1:], {str(self.copy): selection.processing_keys[str(self.copy)]})

        def second_rule(selection, stored):
            calls.append(("second", len(selection.files)))
            return selection

        result = Fliter(rules=[first_rule, second_rule]).filter([self.first, self.copy])
        self.assertEqual(result.files, [self.copy])
        self.assertEqual(calls, ["first", ("second", 1)])
        self.assertEqual(Fliter(rules=[]).filter([self.first, self.copy]).files, [self.first, self.copy])

    def test_path_strings_are_resolved_and_repeated_paths_are_read_once(self):
        with patch("rag_mcp.fliter.fliter.file_processing_key", wraps=file_processing_key) as key:
            result = Fliter().filter([str(self.first), self.first.parent / "." / self.first.name])
        self.assertEqual(result.files, [self.first.resolve()])
        self.assertEqual(key.call_count, 1)

    def test_empty_input_skips_database_access(self):
        with patch.object(Fliter, "_stored_payloads", side_effect=AssertionError("不能读取数据库")):
            self.assertEqual(Fliter().filter([]), FileSelection([], {}))

    def test_invalid_paths_and_read_errors_propagate(self):
        for files in (str(self.first), self.first, [None]):
            with self.subTest(files=files), self.assertRaises(TypeError):
                Fliter().filter(files)
        with self.assertRaises(FileNotFoundError):
            Fliter().filter([self.root / "missing.md"])
        with self.assertRaises(ValueError):
            Fliter().filter([self.write("unsupported.pdf", "text")])

    def test_missing_or_deleted_collection_has_no_stale_keys(self):
        with VectorDatabase(self.root / "db") as db:
            self.assertEqual(Fliter(db).filter([self.first]).files, [self.first])
            db.create_collection("knowledge", 3)
            selection = Fliter().filter([self.first])
            db.upsert("knowledge", [make_embed(self.first)], processing_keys=selection.processing_keys)
            self.assertEqual(Fliter(db).filter([self.first, self.copy]).files, [])
            self.assertEqual(Fliter(db, "other").filter([self.first]).files, [self.first])
            db.client.delete_collection("knowledge")
            self.assertEqual(Fliter(db).filter([self.first]).files, [self.first])

    def test_changed_profile_does_not_skip_existing_file(self):
        with VectorDatabase(self.root / "db") as db:
            db.create_collection("knowledge", 3)
            selection = Fliter().filter([self.first])
            db.upsert("knowledge", [make_embed(self.first)], processing_keys=selection.processing_keys)
            profile = ProcessingProfile(chunk_size=100)
            self.assertEqual(Fliter(db, profile=profile).filter([self.first]).files, [self.first])

    def test_pagination_reads_only_completion_metadata_without_vectors(self):
        files = [self.write(f"{index}.txt", f"文档 {index}") for index in range(257)]
        selection = Fliter().filter(files)
        with VectorDatabase(self.root / "db") as db:
            db.create_collection("knowledge", 3)
            db.upsert("knowledge", [make_embed(file) for file in files], processing_keys=selection.processing_keys)
            with patch.object(db.client, "scroll", wraps=db.client.scroll) as scroll:
                self.assertEqual(Fliter(db).filter(files).files, [])
            self.assertEqual(scroll.call_count, 2)
            for call in scroll.call_args_list:
                self.assertFalse(call.kwargs["with_vectors"])
                self.assertNotIn("text", call.kwargs["with_payload"])
                self.assertEqual(call.kwargs["limit"], 256)


class StoredProcessingKeyTests(unittest.TestCase):
    def test_only_complete_documents_are_recognized(self):
        first, second = payload(), payload(index=1)
        self.assertEqual(stored_processing_keys([first]), set())
        self.assertEqual(stored_processing_keys([first, second]), {first["processing_key"]})
        self.assertEqual(stored_processing_keys([second, first, first]), {first["processing_key"]})

    def test_duplicate_indices_do_not_complete_partial_document(self):
        self.assertEqual(stored_processing_keys([payload(), payload(), payload()]), set())

    def test_separate_sources_versions_attempts_and_counts_cannot_be_combined(self):
        for other in (
            payload(source="/b.md", index=1),
            payload(key="sha256:file-v1:other", index=1),
            payload(ingestion="run-2", index=1),
            payload(count=3, index=1),
        ):
            with self.subTest(other=other):
                self.assertEqual(stored_processing_keys([payload(), other]), set())

    def test_legacy_and_invalid_payloads_are_ignored(self):
        invalid = [
            {},
            {"document_fingerprint": "sha256:document-v1:old", "source": "/a.md", "text": "正文"},
            payload(key="old-key"),
            payload(index=True),
            payload(count=True),
            payload(count=0),
            payload(index=-1),
            payload(index=2),
            payload(ingestion=""),
            payload(source=None),
        ]
        self.assertEqual(stored_processing_keys(invalid), set())


if __name__ == "__main__":
    unittest.main()
