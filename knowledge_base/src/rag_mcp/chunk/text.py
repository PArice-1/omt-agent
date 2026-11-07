"""按 TXT 独立规则递归切分，不解释 Markdown 语法。"""

from pathlib import Path

from chonkie import RecursiveChunker

from ._shared import SourceDocument
from .rules import DEFAULT_CHUNK_SIZE, MIN_CHARACTERS_PER_CHUNK, TEXT_RULES
from .schema import Chunk


def _text_chunker(chunk_size: int) -> RecursiveChunker:
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int):
        raise TypeError("chunk_size 必须是整数")
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")
    return RecursiveChunker(
        tokenizer="character",
        chunk_size=chunk_size,
        rules=TEXT_RULES,
        min_characters_per_chunk=MIN_CHARACTERS_PER_CHUNK,
    )


def text_parser(file: str | Path, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[Chunk]:
    """读取 UTF-8 文本，返回 heading_path 为 [] 的原文片段。"""
    document = SourceDocument.read(file)
    return document.split(_text_chunker(chunk_size), 0, len(document.text), [])
