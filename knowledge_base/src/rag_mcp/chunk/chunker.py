"""按文件后缀调度具体的切分函数。"""

from pathlib import Path

from .markdown import markdown_parser
from .parquet import parquet_parser
from .rules import DEFAULT_CHUNK_SIZE
from .schema import Chunk
from .text import text_parser

_PARSERS = {".md": markdown_parser, ".txt": text_parser, ".parquet": parquet_parser}


class Chunker:
    """文件切分入口；chunk_size 为每个片段的最大字符数。"""

    def __init__(self, chunk_size: int = DEFAULT_CHUNK_SIZE) -> None:
        if isinstance(chunk_size, bool) or not isinstance(chunk_size, int):
            raise TypeError("chunk_size 必须是整数")
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须大于 0")
        self.chunk_size = chunk_size

    def chunk[PathType: str | Path](
        self,
        file_path: str | Path | list[PathType],
        suffix: str | None = None,
    ) -> list[Chunk]:
        """传入单个文件或文件列表，返回按文件顺序合并的 list[Chunk]。

        空列表返回 []。省略后缀时逐文件推断，可混合 MD/TXT/Parquet；显式后缀
        应用于所有文件。后缀不区分大小写，接受 md/.md、txt/.txt、parquet/.parquet。
        不支持的类型抛出 ValueError；路径、读取和解码错误直接抛出。
        """
        files = file_path if isinstance(file_path, list) else [file_path]
        if any(not isinstance(file, (str, Path)) for file in files):
            raise TypeError("file_path 必须是文件路径或文件路径列表")
        return [chunk for file in files for chunk in self._chunk_file(file, suffix)]

    def _chunk_file(self, file_path: str | Path, suffix: str | None) -> list[Chunk]:
        file = Path(file_path)
        suffix = file.suffix if suffix is None else suffix
        suffix = "." + suffix.lower().lstrip(".")
        parser = _PARSERS.get(suffix)
        if parser is None:
            raise ValueError(f"不支持的文件后缀：{suffix}，目前支持 .md、.txt 和 .parquet")
        return parser(file, chunk_size=self.chunk_size)
