"""切分前执行文件过滤规则，统一读取已完整入库的处理标识。"""

from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

from ..vector_databbase import VectorDatabase
from .duplicate import file_processing_key, remove_duplicates, stored_processing_keys
from .schema import FileSelection, ProcessingProfile

type FilterRule = Callable[[FileSelection, set[str]], FileSelection]


class Fliter:
    """输入文件路径，输出待切分文件；db=None 时仅对本批输入去重。"""

    def __init__(
        self,
        db: VectorDatabase | None = None,
        collection_name: str = "knowledge",
        *,
        profile: ProcessingProfile | None = None,
        rules: Sequence[FilterRule] | None = None,
    ) -> None:
        self.db = db
        self.collection_name = collection_name
        self.profile = profile if profile is not None else ProcessingProfile()
        self.rules = tuple(rules) if rules is not None else (remove_duplicates,)

    def filter(self, files: Sequence[str | Path]) -> FileSelection:
        """读取文件计算标识但不解析、切分；构建期间源文件必须保持不变。"""
        if isinstance(files, (str, Path)):
            raise TypeError("files 必须是文件路径序列")
        if any(not isinstance(file, (str, Path)) for file in files):
            raise TypeError("files 中的元素必须是 str 或 Path")
        if not files:
            return FileSelection([], {})
        paths = list(dict.fromkeys(Path(file).expanduser().resolve() for file in files))
        keys = {str(file): file_processing_key(file, self.profile) for file in paths}
        stored = stored_processing_keys(self._stored_payloads())
        result = FileSelection(paths, keys)
        for rule in self.rules:
            result = rule(result, stored)
        return result

    def _stored_payloads(self) -> Iterator[dict[str, Any]]:
        if self.db is None or not self.db.client.collection_exists(self.collection_name):
            return
        offset = None
        while True:
            points, offset = self.db.client.scroll(
                collection_name=self.collection_name,
                limit=256,
                offset=offset,
                with_payload=[
                    "source", "processing_key", "ingestion_id", "chunk_index", "chunk_count",
                ],
                with_vectors=False,
            )
            for point in points:
                if point.payload is not None:
                    yield point.payload
            if offset is None:
                break
