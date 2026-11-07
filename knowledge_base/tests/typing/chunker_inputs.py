"""供静态类型检查验证 Chunker 支持的单路径和路径列表输入。"""

from pathlib import Path
from typing import assert_type

from rag_mcp.chunk import Chunk, Chunker


def check_chunker_inputs(
    paths: list[Path], strings: list[str], mixed: list[str | Path]
) -> None:
    chunker = Chunker()
    assert_type(chunker.chunk(paths), list[Chunk])
    assert_type(chunker.chunk(strings), list[Chunk])
    assert_type(chunker.chunk(mixed), list[Chunk])
    assert_type(chunker.chunk(Path("guide.md")), list[Chunk])
    assert_type(chunker.chunk("guide.md"), list[Chunk])
