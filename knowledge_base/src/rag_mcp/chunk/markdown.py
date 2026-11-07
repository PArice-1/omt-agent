"""识别 Markdown 标题层级，并递归切分每个章节的正文。"""

from pathlib import Path

from chonkie import RecursiveChunker
from markdown_it import MarkdownIt

from ._shared import SourceDocument, _check_is_file
from .rules import DEFAULT_CHUNK_SIZE, MARKDOWN_RULES, MIN_CHARACTERS_PER_CHUNK
from .schema import Chunk


def markdown_parser(
    file: str | Path, *, chunk_size: int = DEFAULT_CHUNK_SIZE
) -> list[Chunk]:
    """按顶层 h1–h6 分章，再按固定规则切分；标题保存到 metadata。

    支持 ATX 和 Setext 标题；代码块、引用、列表中的标题不作为章节边界。
    保留正文的格式和换行，跳过空白章节，前言使用空标题路径。
    """
    document = SourceDocument.read(file)
    chunker = RecursiveChunker(
        tokenizer="character",
        chunk_size=chunk_size,
        rules=MARKDOWN_RULES,
        min_characters_per_chunk=MIN_CHARACTERS_PER_CHUNK,
    )
    tokens = MarkdownIt("commonmark").parse(document.text)
    chunks: list[Chunk] = []
    heading_stack: list[tuple[int, str]] = []
    body_start = 0

    def append_chunks(end: int) -> None:
        chunks.extend(
            document.split(chunker, body_start, end, [title for _, title in heading_stack])
        )

    for index, token in enumerate(tokens):
        if token.type != "heading_open" or token.level != 0 or token.map is None:
            continue

        heading_start, heading_end = token.map
        append_chunks(document.line_offset(heading_start))
        heading_level = int(token.tag[1:])
        while heading_stack and heading_stack[-1][0] >= heading_level:
            heading_stack.pop()
        heading_stack.append((heading_level, tokens[index + 1].content))
        body_start = document.line_offset(heading_end)

    append_chunks(len(document.text))
    return chunks


def parse_md_list(files: list[Path]) -> list[Chunk]:
    """按输入顺序合并多个 Markdown 文件的片段；先校验所有文件。"""
    for file in files:
        _check_is_file(file.expanduser().resolve())
    return [chunk for file in files for chunk in markdown_parser(file)]
