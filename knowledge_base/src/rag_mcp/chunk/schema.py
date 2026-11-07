"""文件切分的统一输出类型。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkMetadata:
    """来源与定位信息。

    source 在文件知识库中是文件绝对路径，在评估中可保存原始资料 ID。
    行号和字符偏移均从 0 开始、结束位置不包含；
    行范围覆盖片段涉及的所有行，精确原文使用 [start_index:end_index] 定位。
    heading_path 按父标题到子标题排列，无标题时为 []。
    """

    source: str
    heading_path: list[str]
    start_line: int
    end_line: int
    start_index: int
    end_index: int


@dataclass(frozen=True)
class Chunk:
    """原文片段及其元数据，可用 dataclasses.asdict() 转成字典。"""

    text: str
    metadata: ChunkMetadata
