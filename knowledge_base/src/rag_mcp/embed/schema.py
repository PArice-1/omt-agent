"""向量化后的统一输出类型。"""

from dataclasses import dataclass

from ..chunk.schema import ChunkMetadata


@dataclass(frozen=True)
class EmbedMetadata(ChunkMetadata):
    """继承 chunk 的来源与定位信息，并在元数据中保留原始正文。"""

    text: str


@dataclass(frozen=True)
class Embed:
    """一个片段的向量及元数据，可用 dataclasses.asdict() 转成字典。"""

    vector: list[float]
    metadata: EmbedMetadata
