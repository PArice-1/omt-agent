import copy
import io
import json
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import call, patch
from urllib.error import URLError

from rag_mcp.chunk import Chunk, Chunker, ChunkMetadata
from rag_mcp.embed import Embed, Embeder, EmbedMetadata


def make_chunk(text: str = "正文。\n", heading_path: list[str] | None = None) -> Chunk:
    return Chunk(
        text=text,
        metadata=ChunkMetadata(
            source="/knowledge-base/guide.md",
            heading_path=["指南", "安装"] if heading_path is None else heading_path,
            start_line=2,
            end_line=3,
            start_index=11,
            end_index=11 + len(text),
        ),
    )


class EmbederTests(unittest.TestCase):
    @patch("rag_mcp.embed.embeder.embed_text", return_value=[0.25, -0.5])
    def test_single_chunk_returns_vector_and_metadata_with_original_text(self, embed_text):
        chunk = make_chunk()
        original = copy.deepcopy(chunk)
        result = Embeder().embed(chunk)
        self.assertIsInstance(result, Embed)
        self.assertIsInstance(result.metadata, EmbedMetadata)
        self.assertEqual(result.vector, [0.25, -0.5])
        self.assertEqual(asdict(result.metadata), {**asdict(chunk.metadata), "text": chunk.text})
        self.assertEqual(set(asdict(result)), {"vector", "metadata"})
        self.assertEqual(json.loads(json.dumps(asdict(result))), asdict(result))
        self.assertEqual(chunk, original)
        embed_text.assert_called_once_with(text="指南 > 安装\n\n正文。\n")

    @patch("rag_mcp.embed.embeder.embed_text", side_effect=[[0.1], [0.2]])
    def test_chunk_list_preserves_order_and_heading_context(self, embed_text):
        first = make_chunk("第一段。")
        second = make_chunk("第二段。", heading_path=[])
        result = Embeder().embed([second, first])
        self.assertIsInstance(result, list)
        self.assertEqual([item.vector for item in result], [[0.1], [0.2]])
        self.assertEqual([item.metadata.text for item in result], ["第二段。", "第一段。"])
        self.assertEqual([item.metadata.heading_path for item in result], [[], ["指南", "安装"]])
        self.assertEqual(
            embed_text.call_args_list,
            [call(text="第二段。"), call(text="指南 > 安装\n\n第一段。")],
        )

    @patch("rag_mcp.embed.embeder.embed_text", return_value=[0.1])
    def test_one_element_list_still_returns_list(self, embed_text):
        results = Embeder().embed([make_chunk()])
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], Embed)

    @patch("rag_mcp.embed.embeder.embed_text")
    def test_empty_list_does_not_request_model(self, embed_text):
        self.assertEqual(Embeder().embed([]), [])
        embed_text.assert_not_called()

    @patch("rag_mcp.embed.embeder.embed_text")
    def test_invalid_input_types_fail_before_model_request(self, embed_text):
        chunk = make_chunk()
        for value in (None, "正文", 42, (chunk,), [chunk, "正文"]):
            with self.subTest(value=value), self.assertRaises(TypeError):
                Embeder().embed(value)
        embed_text.assert_not_called()

    @patch("rag_mcp.embed.embeder.embed_text")
    def test_invalid_chunk_text_fails_before_any_batch_request(self, embed_text):
        for value, error in (("", ValueError), (" \n\t", ValueError), (None, TypeError)):
            chunk = replace(make_chunk(), text=value)
            for chunks in (chunk, [make_chunk(), chunk]):
                with self.subTest(text=value, is_batch=isinstance(chunks, list)):
                    with self.assertRaises(error):
                        Embeder().embed(chunks)
        embed_text.assert_not_called()

    @patch("rag_mcp.embed.embeder.embed_text", return_value=[0.1])
    def test_result_heading_paths_are_independent_of_input_and_other_results(self, embed_text):
        chunk = make_chunk()
        results = Embeder().embed([chunk, chunk])
        results[0].metadata.heading_path.append("新增")
        self.assertEqual(chunk.metadata.heading_path, ["指南", "安装"])
        self.assertEqual(results[1].metadata.heading_path, ["指南", "安装"])

    @patch("rag_mcp.embed.embeder.embed_text", side_effect=URLError("服务不可用"))
    def test_model_errors_propagate(self, embed_text):
        with self.assertRaises(URLError):
            Embeder().embed(make_chunk())
        with self.assertRaises(URLError):
            Embeder().embed([make_chunk()])

    @patch("rag_mcp.embed.ollama.urlopen")
    def test_file_list_can_be_chunked_then_embedded_with_real_backend_parser(self, urlopen):
        urlopen.side_effect = [
            io.BytesIO(json.dumps({"embeddings": [[0.25, 1]]}).encode()),
            io.BytesIO(json.dumps({"embeddings": [[0.5, 2]]}).encode()),
        ]
        with TemporaryDirectory() as directory:
            markdown = Path(directory) / "guide.md"
            text = Path(directory) / "notes.txt"
            markdown.write_text("# 指南\n正文。\n", encoding="utf-8")
            text.write_text("纯文本。", encoding="utf-8")
            chunks = Chunker().chunk([markdown, text])
            results = Embeder().embed(chunks)
            self.assertEqual([result.vector for result in results], [[0.25, 1.0], [0.5, 2.0]])
            self.assertEqual([result.metadata.text for result in results], ["正文。\n", "纯文本。"])
            for chunk, result in zip(chunks, results):
                self.assertEqual(asdict(result.metadata), {**asdict(chunk.metadata), "text": chunk.text})
            self.assertEqual(
                [json.loads(item.args[0].data)["input"] for item in urlopen.call_args_list],
                ["指南\n\n正文。\n", "纯文本。"],
            )


if __name__ == "__main__":
    unittest.main()
