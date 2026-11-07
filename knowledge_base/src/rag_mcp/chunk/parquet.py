"""通用 Parquet 正文读取与切分；不包含数据集标注、embedding 或入库规则。"""

from collections.abc import Iterator
from pathlib import Path

from ._shared import SourceDocument, _check_is_file
from .rules import DEFAULT_CHUNK_SIZE
from .schema import Chunk
from .text import _text_chunker


def iter_parquet_chunks(
    file: str | Path,
    *,
    id_column: str = "id",
    text_column: str = "text",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    batch_size: int = 1000,
    max_documents: int | None = None,
) -> Iterator[Chunk]:
    """逐行将正文按 TXT 规则切分，source 保留原始 ID 的字符串形式。

    列名可配置；整数或非空字符串 ID 均可，不按正文去重，所选重复 ID 报错。
    max_documents 限制原始行数，不是片段数。按批读取、逐篇切分；缓存一批
    Parquet 记录、一篇资料的片段和已见 ID 集合，不缓存全文件的片段。
    字符位置与行号相对于该行原始正文，不是 Parquet 二进制文件位置。
    pyarrow 仅在消费本迭代器时导入，不影响普通 MD/TXT 的运行环境。
    """
    if type(batch_size) is not int or batch_size <= 0:
        raise ValueError("batch_size 必须是正整数")
    if max_documents is not None and (type(max_documents) is not int or max_documents <= 0):
        raise ValueError("max_documents 必须是正整数或 None")
    if any(not isinstance(name, str) or not name.strip() for name in (id_column, text_column)):
        raise ValueError("id_column 和 text_column 必须为非空列名")
    if id_column == text_column:
        raise ValueError("ID 列和正文列不能相同")
    chunker = _text_chunker(chunk_size)
    path = Path(file).expanduser().resolve()
    _check_is_file(path)
    try:
        import pyarrow.parquet as pq
    except ModuleNotFoundError as exc:
        if exc.name not in ("pyarrow", "pyarrow.parquet"):
            raise
        raise ImportError("Parquet 支持需要 pyarrow；本项目可运行 uv sync --group eval") from exc

    seen: set[str] = set()
    with pq.ParquetFile(path) as parquet:
        missing = {id_column, text_column} - set(parquet.schema_arrow.names)
        if missing:
            raise ValueError(f"{path.name} 缺少字段：{', '.join(sorted(missing))}")
        for batch in parquet.iter_batches(batch_size=batch_size, columns=[id_column, text_column]):
            for row in batch.to_pylist():
                value = row[id_column]
                if type(value) not in (str, int) or not str(value).strip():
                    raise ValueError(f"{path.name}: {id_column} 必须是非空字符串或整数 ID")
                source = str(value)
                if source in seen:
                    raise ValueError(f"{path.name} 存在重复资料 ID：{source}")
                text = row[text_column]
                if not isinstance(text, str) or not text.strip():
                    raise ValueError(f"{path.name}: 资料 ID={source} 的正文不能为空或只有空白")
                seen.add(source)
                document = SourceDocument.from_text(text, source=source)
                chunks = document.split(chunker, 0, len(text), [])
                if not chunks:
                    raise ValueError(f"资料 ID={source} 未产生有效片段")
                yield from chunks
                if max_documents is not None and len(seen) >= max_documents:
                    return


def parquet_parser(file: str | Path, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[Chunk]:
    """与 Chunker.chunk 兼容的小文件入口；大文件请使用 iter_parquet_chunks。"""
    return list(iter_parquet_chunks(file, chunk_size=chunk_size))
