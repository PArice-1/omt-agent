import json
import os
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from rag_mcp.chunk import (
    Chunk,
    Chunker,
    markdown_parser,
    parse_md_list,
    search_files,
    search_md_files,
    text_parser,
)


class MarkdownParserTests(unittest.TestCase):
    def parse(self, text: str) -> list[Chunk]:
        with TemporaryDirectory() as directory:
            file = Path(directory) / "demo.md"
            file.write_text(text, encoding="utf-8", newline="")
            chunks = markdown_parser(file)
            lines = text.splitlines(keepends=True)
            for chunk in chunks:
                metadata = chunk.metadata
                self.assertEqual(metadata.source, str(file.resolve()))
                self.assertEqual(
                    chunk.text,
                    "".join(lines[metadata.start_line:metadata.end_line]),
                )
                self.assertEqual(chunk.text, text[metadata.start_index:metadata.end_index])
            return chunks

    def test_heading_hierarchy_and_siblings(self):
        chunks = self.parse(
            "# 指南\n\n介绍。\n\n"
            "## 环境\n\n需要 Python。\n\n"
            "### 安装\n\n安装依赖。\n\n"
            "## 检查\n\n导入模块。\n"
        )
        self.assertEqual(
            [chunk.metadata.heading_path for chunk in chunks],
            [["指南"], ["指南", "环境"], ["指南", "环境", "安装"], ["指南", "检查"]],
        )
        self.assertEqual(chunks[0].metadata.start_line, 1)
        self.assertEqual(chunks[0].metadata.end_line, 4)
        self.assertEqual(chunks[-1].text, "\n导入模块。\n")

    def test_preamble_and_headingless_document(self):
        chunks = self.parse("前言。\n\n# 标题\n正文。")
        self.assertEqual([chunk.metadata.heading_path for chunk in chunks], [[], ["标题"]])
        self.assertEqual(chunks[0].text, "前言。\n\n")
        self.assertEqual(chunks[-1].text, "正文。")
        plain = self.parse("没有标题。\n第二行。")
        self.assertEqual(len(plain), 1)
        self.assertEqual(plain[0].metadata.heading_path, [])

    def test_empty_sections_still_update_path(self):
        chunks = self.parse("# 父标题\n\n### 子标题\n正文。\n\n## 空章节\n")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].metadata.heading_path, ["父标题", "子标题"])

    def test_empty_and_whitespace_documents(self):
        for text in ("", "\n \t\n", "# 只有标题\n"):
            with self.subTest(text=text):
                self.assertEqual(self.parse(text), [])

    def test_code_and_nested_headings_are_preserved(self):
        body = (
            "\n```python\n# 代码注释\nprint('hello')\n```\n\n"
            "> ## 引用里的标题\n> 引用正文。\n\n"
            "- ### 列表里的标题\n\n"
            "    # 缩进代码\n"
        )
        chunks = self.parse("# 示例\n" + body)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, body)

    def test_setext_headings_and_inline_formatting(self):
        chunks = self.parse("指南\n====\n介绍。\n\n安装 **依赖**\n----\n运行命令。\n")
        self.assertEqual(
            [chunk.metadata.heading_path for chunk in chunks],
            [["指南"], ["指南", "安装 **依赖**"]],
        )
        self.assertEqual(chunks[0].metadata.start_line, 2)
        self.assertEqual(chunks[-1].metadata.start_line, 6)

    def test_original_line_endings_are_preserved(self):
        chunks = self.parse("# 标题\r\n\r\n正文。\r\n")
        self.assertEqual(chunks[0].text, "\r\n正文。\r\n")
        self.assertEqual((chunks[0].metadata.start_line, chunks[0].metadata.end_line), (1, 3))

    def test_new_top_level_heading_resets_path(self):
        chunks = self.parse("# 旧章节\n## 子章节\n旧正文。\n# 新章节\n新正文。")
        self.assertEqual(
            [chunk.metadata.heading_path for chunk in chunks],
            [["旧章节", "子章节"], ["新章节"]],
        )

    def test_missing_file(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                markdown_parser(Path(directory) / "missing.md")

    def test_directory_is_not_a_document(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(IsADirectoryError):
                markdown_parser(Path(directory))


class ParseMarkdownListTests(unittest.TestCase):
    def test_combines_multiple_files_into_flat_chunk_list(self):
        with TemporaryDirectory() as directory:
            first = Path(directory) / "first.md"
            second = Path(directory) / "second.md"
            first.write_text("# A\n正文 A。\n## B\n正文 B。\n", encoding="utf-8")
            second.write_text("# C\n正文 C。\n", encoding="utf-8")
            chunks = parse_md_list([first, second])
            self.assertEqual(chunks, markdown_parser(first) + markdown_parser(second))
            self.assertEqual(len(chunks), 3)
            self.assertTrue(all(isinstance(chunk, Chunk) for chunk in chunks))

    def test_empty_document_does_not_prevent_parsing_next_file(self):
        with TemporaryDirectory() as directory:
            empty = Path(directory) / "empty.md"
            document = Path(directory) / "document.md"
            empty.touch()
            document.write_text("# 标题\n正文。\n", encoding="utf-8")
            self.assertEqual(parse_md_list([empty, document]), markdown_parser(document))

    def test_empty_file_list(self):
        self.assertEqual(parse_md_list([]), [])


class ChunkerTests(unittest.TestCase):
    def parse(self, text: str, suffix: str, chunk_size: int = 2048) -> list[Chunk]:
        with TemporaryDirectory() as directory:
            file = Path(directory) / f"demo{suffix}"
            file.write_text(text, encoding="utf-8", newline="")
            chunks = Chunker(chunk_size=chunk_size).chunk(file, suffix)
            previous_end = 0
            for chunk in chunks:
                metadata = chunk.metadata
                self.assertEqual(metadata.source, str(file.resolve()))
                self.assertIsInstance(metadata.heading_path, list)
                self.assertEqual(chunk.text, text[metadata.start_index:metadata.end_index])
                self.assertLessEqual(len(chunk.text), chunk_size)
                self.assertGreaterEqual(metadata.start_index, previous_end)
                self.assertGreater(metadata.end_line, metadata.start_line)
                previous_end = metadata.end_index
            return chunks

    def test_dispatch_accepts_paths_and_normalized_suffixes(self):
        with TemporaryDirectory() as directory:
            file = Path(directory) / "demo.MD"
            file.write_text("# 标题\n正文。\n", encoding="utf-8")
            chunker = Chunker()
            expected = markdown_parser(file)
            self.assertEqual(chunker.chunk(file), expected)
            self.assertEqual(chunker.chunk(str(file), "MD"), expected)
            self.assertEqual(chunker.chunk(os.path.relpath(file), ".md"), expected)
            # 显式后缀决定解析函数，也允许解析没有常规扩展名的文件。
            self.assertEqual(chunker.chunk(file, "TXT"), text_parser(file))

    def test_file_list_combines_mixed_formats_in_input_order(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            markdown = root / "guide.MD"
            text = root / "notes.txt"
            empty = root / "empty.md"
            markdown.write_text("# 指南\n第一节。\n## 安装\n第二节。", encoding="utf-8")
            text.write_text("# 纯文本\n第三节。", encoding="utf-8")
            empty.touch()
            chunker = Chunker(chunk_size=8)
            chunks = chunker.chunk([str(text), empty, markdown])
            self.assertEqual(chunks, chunker.chunk(text) + chunker.chunk(markdown))
            self.assertTrue(all(isinstance(chunk, Chunk) for chunk in chunks))
            self.assertEqual(chunks[0].metadata.source, str(text.resolve()))
            self.assertEqual(chunks[-1].metadata.source, str(markdown.resolve()))

    def test_file_list_uses_explicit_suffix_for_each_file(self):
        with TemporaryDirectory() as directory:
            files = [Path(directory) / name for name in ("first.data", "second")]
            for file in files:
                file.write_text("# 指南\n正文。", encoding="utf-8")
            chunks = Chunker().chunk(files, "MD")
            self.assertEqual([chunk.text for chunk in chunks], ["正文。", "正文。"])
            self.assertEqual([chunk.metadata.heading_path for chunk in chunks], [["指南"], ["指南"]])

    def test_empty_file_list(self):
        self.assertEqual(Chunker().chunk([]), [])

    def test_one_file_list_matches_single_file(self):
        with TemporaryDirectory() as directory:
            file = Path(directory) / "notes.txt"
            file.write_text("重复正文" * 20, encoding="utf-8")
            chunker = Chunker(chunk_size=10)
            self.assertEqual(chunker.chunk([file]), chunker.chunk(file))

    def test_invalid_file_input_types(self):
        for value in (None, 42, ("notes.txt",), ["notes.txt", None]):
            with self.subTest(value=value), self.assertRaises(TypeError):
                Chunker().chunk(value)

    def test_file_list_propagates_errors(self):
        with TemporaryDirectory() as directory:
            file = Path(directory) / "notes.txt"
            file.touch()
            with self.assertRaises(FileNotFoundError):
                Chunker().chunk([file, Path(directory) / "missing.md"])
            with self.assertRaises(ValueError):
                Chunker().chunk([file, Path(directory) / "unsupported.pdf"])

    def test_unsupported_suffix_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不支持的文件后缀"):
            Chunker().chunk("demo.pdf", ".pdf")

    def test_invalid_chunk_sizes_are_rejected(self):
        for size, error in ((0, ValueError), (-1, ValueError), (1.5, TypeError), (True, TypeError)):
            with self.subTest(size=size), self.assertRaises(error):
                Chunker(chunk_size=size)

    def test_schema_has_text_and_json_serializable_metadata(self):
        chunk = self.parse("正文。", ".txt")[0]
        data = asdict(chunk)
        self.assertEqual(set(data), {"text", "metadata"})
        self.assertEqual(
            data["metadata"],
            {
                "source": chunk.metadata.source,
                "heading_path": [],
                "start_line": 0,
                "end_line": 1,
                "start_index": 0,
                "end_index": 3,
            },
        )
        self.assertEqual(json.loads(json.dumps(data)), data)

    def test_txt_preserves_markdown_syntax_as_plain_text(self):
        text = "# 这不是标题\n\n## 也不是章节\n普通正文。"
        chunks = self.parse(text, ".TXT")
        self.assertEqual([chunk.text for chunk in chunks], [text])
        self.assertEqual(chunks[0].metadata.heading_path, [])

    def test_txt_empty_and_whitespace_documents(self):
        for text in ("", " \n\t\r\n"):
            with self.subTest(text=text):
                self.assertEqual(self.parse(text, ".txt"), [])

    def test_long_unbroken_chinese_text_is_split_without_loss(self):
        text = "重复内容" * 20
        for suffix in (".md", ".txt"):
            with self.subTest(suffix=suffix):
                chunks = self.parse(text, suffix, chunk_size=7)
                self.assertGreater(len(chunks), 1)
                self.assertEqual("".join(chunk.text for chunk in chunks), text)
                self.assertEqual(
                    [(chunk.metadata.start_line, chunk.metadata.end_line) for chunk in chunks],
                    [(0, 1)] * len(chunks),
                )

    def test_recursive_rules_prefer_paragraph_boundaries(self):
        text = "第一段。\n\n第二段。\n\n第三段。\n"
        for suffix in (".md", ".txt"):
            with self.subTest(suffix=suffix):
                chunks = self.parse(text, suffix, chunk_size=8)
                self.assertEqual(
                    [chunk.text for chunk in chunks],
                    ["第一段。\n\n", "第二段。\n\n", "第三段。\n"],
                )
                self.assertEqual(
                    [(chunk.metadata.start_line, chunk.metadata.end_line) for chunk in chunks],
                    [(0, 2), (2, 4), (4, 5)],
                )

    def test_recursive_rules_handle_chinese_and_english_punctuation(self):
        for text, expected in (
            ("一。二。三。四。五。", ["一。二。", "三。四。", "五。"]),
            ("One. Two. End.", ["One. ", "Two. ", "End."]),
        ):
            for suffix in (".md", ".txt"):
                with self.subTest(text=text, suffix=suffix):
                    chunks = self.parse(text, suffix, chunk_size=5)
                    self.assertEqual([chunk.text for chunk in chunks], expected)

    def test_long_markdown_sections_inherit_heading_path(self):
        body = "正文内容" * 20
        text = f"# 父标题\n## 子标题\n{body}\n# 另一章\n末尾。"
        chunks = self.parse(text, ".md", chunk_size=12)
        self.assertGreater(len(chunks), 2)
        self.assertEqual("".join(chunk.text for chunk in chunks[:-1]), body + "\n")
        self.assertTrue(
            all(chunk.metadata.heading_path == ["父标题", "子标题"] for chunk in chunks[:-1])
        )
        self.assertEqual(chunks[-1].metadata.heading_path, ["另一章"])
        self.assertEqual(chunks[-1].text, "末尾。")
        chunks[0].metadata.heading_path.append("本片段")
        self.assertEqual(chunks[1].metadata.heading_path, ["父标题", "子标题"])

    def test_long_fenced_code_does_not_create_heading_paths(self):
        body = "```python\n# 代码里的标题\n" + "print('hello')\n" * 10 + "```\n"
        chunks = self.parse("# 示例\n" + body, ".md", chunk_size=20)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunk.text for chunk in chunks), body)
        self.assertTrue(all(chunk.metadata.heading_path == ["示例"] for chunk in chunks))

    def test_crlf_and_cr_line_ranges_and_source_offsets(self):
        for newline in ("\r\n", "\r"):
            for suffix in (".md", ".txt"):
                with self.subTest(newline=newline, suffix=suffix):
                    text = f"甲乙{newline}丙丁{newline}戊己"
                    chunks = self.parse(text, suffix, chunk_size=4)
                    self.assertEqual(
                        [chunk.text for chunk in chunks],
                        [f"甲乙{newline}", f"丙丁{newline}", "戊己"],
                    )
                    self.assertEqual(
                        [(chunk.metadata.start_line, chunk.metadata.end_line) for chunk in chunks],
                        [(0, 1), (1, 2), (2, 3)],
                    )

    def test_missing_files_and_directories_raise(self):
        with TemporaryDirectory() as directory:
            for suffix in (".md", ".txt"):
                with self.subTest(suffix=suffix):
                    with self.assertRaises(FileNotFoundError):
                        Chunker().chunk(Path(directory) / f"missing{suffix}")
                    with self.assertRaises(IsADirectoryError):
                        Chunker().chunk(directory, suffix)


class SearchMarkdownFilesTests(unittest.TestCase):
    def test_search_files_includes_markdown_and_txt_only(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("a.md", "b.TXT", "c.pdf"):
                (root / name).touch()
            self.assertEqual(search_files([root]), [root / "a.md", root / "b.TXT"])

    def test_recursive_sorted_search(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            nested.mkdir()
            for file in (root / "b.md", root / "a.MD", nested / "c.md"):
                file.write_text("正文", encoding="utf-8")
            (root / "notes.txt").write_text("不是 Markdown", encoding="utf-8")
            (root / "folder.md").mkdir()
            (root / "folder.md" / "inside.md").touch()
            self.assertEqual(
                search_md_files([root]),
                sorted(
                    file.resolve()
                    for file in (
                        root / "a.MD",
                        root / "b.md",
                        nested / "c.md",
                        root / "folder.md" / "inside.md",
                    )
                ),
            )

    def test_repeated_and_overlapping_roots_are_deduplicated(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            nested.mkdir()
            file = nested / "demo.md"
            file.touch()
            self.assertEqual(search_md_files([root, root, nested]), [file.resolve()])

    def test_symlink_alias_is_deduplicated(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "original.md"
            file.touch()
            alias = root / "alias.md"
            try:
                alias.symlink_to(file)
            except (OSError, NotImplementedError):
                self.skipTest("当前环境不支持创建符号链接")
            self.assertEqual(search_md_files([root]), [file.resolve()])

    def test_empty_roots_and_directory(self):
        self.assertEqual(search_md_files([]), [])
        with TemporaryDirectory() as directory:
            self.assertEqual(search_md_files([Path(directory)]), [])

    def test_missing_root(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(FileNotFoundError):
                search_md_files([root, root / "missing"])

    def test_file_is_not_a_root_directory(self):
        with TemporaryDirectory() as directory:
            file = Path(directory) / "demo.md"
            file.touch()
            with self.assertRaises(NotADirectoryError):
                search_md_files([file])


if __name__ == "__main__":
    unittest.main()
