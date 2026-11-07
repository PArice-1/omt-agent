import re
import subprocess
import sys
import unittest
from bisect import bisect_left, bisect_right
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

from rag_mcp.chunk import Chunker, iter_parquet_chunks


class ParquetChunkTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "documents.parquet"

    def write(self, values):
        pq.write_table(pa.table(values), self.path)

    def test_long_document_uses_shared_text_rules_and_preserves_exact_locations(self):
        text = "开头\r\n" + "中文abcdefghijklmn。" * 100 + "\r末尾\n"
        source = "../folder/./original-id"
        self.write({"id": [source], "text": [text]})
        chunks = list(iter_parquet_chunks(self.path, chunk_size=32))
        self.assertGreater(len(chunks), 1)
        line_starts = [0] + [match.end() for match in re.finditer(r"\r\n|[\r\n]", text)]
        previous_end = 0
        for chunk in chunks:
            metadata = chunk.metadata
            self.assertEqual(metadata.source, source)
            self.assertEqual(metadata.heading_path, [])
            self.assertLessEqual(len(chunk.text), 32)
            self.assertEqual(text[metadata.start_index:metadata.end_index], chunk.text)
            self.assertFalse(text[previous_end:metadata.start_index].strip())
            self.assertEqual(metadata.start_line, bisect_right(line_starts, metadata.start_index) - 1)
            self.assertEqual(metadata.end_line, bisect_left(line_starts, metadata.end_index))
            previous_end = metadata.end_index
        self.assertFalse(text[previous_end:].strip())

    def test_configurable_columns_and_integer_ids(self):
        self.write({"doc_key": [10, 20], "body": ["正文一", "正文二"]})
        chunks = list(iter_parquet_chunks(self.path, id_column="doc_key", text_column="body"))
        self.assertEqual([chunk.metadata.source for chunk in chunks], ["10", "20"])

    def test_identical_text_under_different_ids_is_not_deduplicated(self):
        self.write({"id": [1, 2], "text": ["相同正文", "相同正文"]})
        self.assertEqual(len(list(iter_parquet_chunks(self.path))), 2)

    def test_max_documents_keeps_every_chunk_of_selected_document(self):
        text = "长正文" * 100
        self.write({"id": [1, 2], "text": [text, None]})
        chunks = list(iter_parquet_chunks(self.path, max_documents=1, chunk_size=10, batch_size=1))
        self.assertGreater(len(chunks), 1)
        self.assertEqual({chunk.metadata.source for chunk in chunks}, {"1"})
        self.assertEqual("".join(chunk.text for chunk in chunks), text)

    def test_duplicate_document_ids_across_batches_are_rejected(self):
        self.write({"id": [1, 1], "text": ["正文一", "正文二"]})
        with self.assertRaisesRegex(ValueError, "重复.*1"):
            list(iter_parquet_chunks(self.path, batch_size=1))

    def test_invalid_ids_or_blank_text_are_rejected(self):
        for values in ({"id": [None], "text": ["正文"]}, {"id": [True], "text": ["正文"]},
                       {"id": [" "], "text": ["正文"]}, {"id": [1], "text": [" \n"]}):
            with self.subTest(values=values):
                self.write(values)
                with self.assertRaises(ValueError):
                    list(iter_parquet_chunks(self.path))

    def test_missing_columns_are_reported(self):
        self.write({"id": [1], "body": ["正文"]})
        with self.assertRaisesRegex(ValueError, "text"):
            list(iter_parquet_chunks(self.path))

    def test_invalid_options(self):
        for options in ({"batch_size": 0}, {"max_documents": True}, {"chunk_size": 0},
                        {"chunk_size": True}, {"id_column": ""}, {"text_column": "id"}):
            with self.subTest(options=options), self.assertRaises((ValueError, TypeError)):
                list(iter_parquet_chunks(self.path, **options))  # pyright: ignore[reportArgumentType]

    def test_chunker_dispatches_parquet_without_changing_the_streaming_output(self):
        self.write({"id": [1], "text": ["正文很长" * 30]})
        self.assertEqual(Chunker(chunk_size=10).chunk(self.path),
                         list(iter_parquet_chunks(self.path, chunk_size=10)))

    def test_iterator_is_lazy(self):
        chunks = iter_parquet_chunks(self.path)
        self.assertIs(iter(chunks), chunks)
        with self.assertRaises(FileNotFoundError):
            next(chunks)

    def test_regular_imports_work_without_pyarrow_and_parquet_explains_missing_dependency(self):
        self.write({"id": [1], "text": ["正文"]})
        code = """
import builtins, sys
original_import = builtins.__import__
def blocked(name, *args, **kwargs):
    if name == 'pyarrow' or name.startswith('pyarrow.'):
        raise ModuleNotFoundError('blocked pyarrow', name='pyarrow')
    return original_import(name, *args, **kwargs)
builtins.__import__ = blocked
from rag_mcp.chunk import Chunker, iter_parquet_chunks
assert Chunker().chunk([]) == []
try:
    list(iter_parquet_chunks(sys.argv[1]))
except ImportError as error:
    assert 'pyarrow' in str(error)
else:
    raise AssertionError('应提示缺少可选依赖')
"""
        result = subprocess.run([sys.executable, "-c", code, str(self.path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
