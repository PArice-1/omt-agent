"""文件过滤的输入配置与输出；不依赖切分结果。"""

from dataclasses import dataclass, field
from pathlib import Path

from ..chunk.rules import DEFAULT_CHUNK_SIZE
from ..embed import ollama


@dataclass(frozen=True)
class ProcessingProfile:
    """影响入库结果的配置；切分规则或标题拼接逻辑改变时需更新版本。"""

    chunk_size: int = DEFAULT_CHUNK_SIZE
    chunk_version: str = "recursive-v1"
    embedding_model: str = field(default_factory=lambda: ollama.MODEL)
    embedding_version: str = "heading-body-v1"

    def __post_init__(self) -> None:
        if type(self.chunk_size) is not int or self.chunk_size <= 0:
            raise ValueError("chunk_size 必须是正整数")


@dataclass(frozen=True)
class FileSelection:
    """待切分文件及其处理标识；字典键与 ChunkMetadata.source 一样是绝对路径。"""

    files: list[Path]
    processing_keys: dict[str, str]
