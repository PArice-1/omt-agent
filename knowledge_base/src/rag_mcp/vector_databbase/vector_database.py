"""将 Embed 转换为 Qdrant Point 并持久保存。"""

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from types import TracebackType
from typing import Self
from uuid import uuid4

from qdrant_client import QdrantClient, models

from ..embed import Embed


class VectorDatabase:
    """通过本地 Qdrant 客户端管理集合和向量，支持 with 自动关闭。"""

    def __init__(self, db_path: str | Path) -> None:
        self.client = QdrantClient(path=str(Path(db_path).expanduser().resolve()))

    def __enter__(self) -> Self:
        """返回当前数据库实例，供 with ... as db 使用。"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """退出上下文时关闭客户端，块内异常继续向上传递。"""
        self.close()

    def create_collection(
        self, collection_name: str, vector_size: int, *, embedding_model: str | None = None
    ) -> bool:
        """创建 Cosine 集合，可记录模型以防混用；同名集合已存在时抛出异常。"""
        return self.client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
            metadata={"embedding_model": embedding_model} if embedding_model else None,
        )

    def check_embedding_model(self, collection_name: str, embedding_model: str) -> None:
        """已记录的模型必须一致；历史集合没有模型信息时由调用者保证兼容。"""
        metadata = self.client.get_collection(collection_name).config.metadata or {}
        stored_model = metadata.get("embedding_model")
        if stored_model and stored_model != embedding_model:
            raise ValueError(
                f"集合使用模型 {stored_model}，当前模型为 {embedding_model}；请使用新集合或原模型"
            )

    def upsert(
        self,
        collection_name: str,
        embeds: list[Embed],
        *,
        processing_keys: Mapping[str, str] | None = None,
    ) -> list[str]:
        """写入片段并按输入顺序返回 Point UUID；空列表返回 []，不访问数据库。

        vector 保存为 Point.vector，metadata 转为字典保存为 Point.payload。
        每次写入都生成新 ID，不按正文或来源去重，也不修改输入。
        可传 source -> 文件处理标识的 processing_keys；必须一次传入各文件的全部片段。
        此时保存处理标识、单次写入 ID、文件内片段编号和总数，供 Fliter 检查完整性。
        不传时保持原 payload 结构。去重由切分前的 Fliter 执行。
        集合需要提前创建，向量维度需匹配；数据库错误直接向上传递。
        """
        if not isinstance(embeds, list):
            raise TypeError("embeds 必须是 list[Embed]")
        if any(not isinstance(item, Embed) for item in embeds):
            raise TypeError("embeds 中的元素必须是 Embed")
        if not embeds:
            return []

        payloads = [asdict(item.metadata) for item in embeds]
        if processing_keys is not None:
            counts = Counter(item.metadata.source for item in embeds)
            indices: dict[str, int] = defaultdict(int)
            ingestion_id = str(uuid4())
            for item, payload in zip(embeds, payloads):
                source = item.metadata.source
                key = processing_keys[source]
                if not isinstance(key, str) or not key.startswith("sha256:file-v1:"):
                    raise ValueError("processing_keys 必须包含版本化的文件处理标识")
                payload.update(
                    processing_key=key,
                    ingestion_id=ingestion_id,
                    chunk_index=indices[source],
                    chunk_count=counts[source],
                )
                indices[source] += 1

        point_ids = [str(uuid4()) for _ in embeds]
        points = [
            models.PointStruct(
                id=point_id,
                vector=item.vector,
                payload=payload,
            )
            for point_id, item, payload in zip(point_ids, embeds, payloads)
        ]
        self.client.upsert(
            collection_name=collection_name,
            points=points,
            wait=True,
        )
        return point_ids

    def close(self) -> None:
        """关闭客户端，释放本地数据库文件锁。"""
        self.client.close()
