"""Markdown/TXT/Parquet 切分，统一返回 text + metadata。"""

from .chunker import Chunker
from .files import search_files, search_md_files
from .markdown import markdown_parser, parse_md_list
from .parquet import iter_parquet_chunks, parquet_parser
from .schema import Chunk, ChunkMetadata
from .text import text_parser

__all__ = [
    "Chunk",
    "ChunkMetadata",
    "Chunker",
    "iter_parquet_chunks",
    "parquet_parser",
    "markdown_parser",
    "parse_md_list",
    "search_files",
    "search_md_files",
    "text_parser",
]
