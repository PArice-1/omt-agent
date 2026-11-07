"""读取原文，并将 Chonkie 的局部偏移映射到文件位置。"""

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from pathlib import Path

from chonkie import RecursiveChunker

from .schema import Chunk, ChunkMetadata


def _check_is_file(file: Path) -> None:
    if not file.exists():
        raise FileNotFoundError(f"{file} 路径不存在")
    if file.is_dir():
        raise IsADirectoryError(f"{file} 是目录，不是文件")
    if not file.is_file():
        raise ValueError(f"{file} 不是普通文件")


@dataclass(frozen=True)
class SourceDocument:
    source: str
    text: str
    line_starts: list[int]

    @classmethod
    def read(cls, file: str | Path) -> "SourceDocument":
        file = Path(file).expanduser().resolve()
        _check_is_file(file)
        # 保留 CRLF/CR，不清洗正文，以便字符偏移准确定位原文。
        with file.open(encoding="utf-8", newline="") as stream:
            text = stream.read()
        return cls.from_text(text, source=str(file))

    @classmethod
    def from_text(cls, text: str, *, source: str) -> "SourceDocument":
        """为内存正文建立定位索引，source 可以是文件路径或原始资料 ID。"""
        if not isinstance(text, str):
            raise TypeError("text 必须是字符串")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source 必须是非空字符串")
        line_starts = [0] + [match.end() for match in re.finditer(r"\r\n|[\r\n]", text)]
        return cls(source=source, text=text, line_starts=line_starts)

    def line_offset(self, line: int) -> int:
        """将 Markdown 解析器的行边界换算为原文字符偏移，包含 EOF。"""
        return self.line_starts[line] if line < len(self.line_starts) else len(self.text)

    def split(
        self,
        chunker: RecursiveChunker,
        start: int,
        end: int,
        heading_path: list[str],
    ) -> list[Chunk]:
        """切分一个正文区间；同章的所有子片段继承独立的标题路径列表。"""
        body = self.text[start:end]
        if not body.strip():
            return []

        chunks: list[Chunk] = []
        for part in chunker.chunk(body):
            if not part.text.strip():
                continue
            start_index = start + part.start_index
            end_index = start + part.end_index
            chunks.append(
                Chunk(
                    text=part.text,
                    metadata=ChunkMetadata(
                        source=self.source,
                        heading_path=list(heading_path),
                        start_line=bisect_right(self.line_starts, start_index) - 1,
                        end_line=bisect_left(self.line_starts, end_index),
                        start_index=start_index,
                        end_index=end_index,
                    ),
                )
            )
        return chunks
