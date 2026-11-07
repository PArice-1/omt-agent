"""读取持久化知识库；搜索不会扫描源文件或重新生成文档向量。"""

import math
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import UUID

from qdrant_client import models

from ..config import DEFAULT_COLLECTION, DEFAULT_DB_PATH
from ..embed import ollama
from ..fliter.duplicate import stored_processing_keys
from ..vector_databbase import VectorDatabase

_PUBLIC_FIELDS = (
    "source", "heading_path", "text", "start_line", "end_line", "start_index", "end_index",
    "processing_key", "ingestion_id", "chunk_index", "chunk_count",
)
_STATE_FIELDS = ("source", "processing_key", "ingestion_id", "chunk_index", "chunk_count")


def _pagination(limit: int, offset: int = 0) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit 必须是 1 到 100 的整数")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset 必须是非负整数")


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须是非空字符串")


def _filter(**fields: str | None) -> models.Filter | None:
    conditions = []
    for name, value in fields.items():
        if value is not None:
            _text(value, name)
            conditions.append(models.FieldCondition(key=name, match=models.MatchValue(value=value)))
    return models.Filter(must=conditions) if conditions else None


def _public(point: Any) -> dict[str, Any]:
    payload = point.payload or {}
    return {"id": str(point.id), **{key: payload[key] for key in _PUBLIC_FIELDS if key in payload}}


def _page(items: list[Any], limit: int, offset: int) -> dict[str, Any]:
    return {
        "items": items[offset:offset + limit],
        "total": len(items),
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < len(items),
    }


class KnowledgeBase:
    """以一个存储目录和集合为作用域；每次操作关闭客户端，实例内串行访问。

    不存在的知识库按空库读取，不创建目录。其他进程不可同时操作相同本地数据库。
    文档读取只访问已入库 payload，不会按用户提供的 source 读取磁盘文件。
    """

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        _text(collection_name, "collection_name")
        self.db_path = Path(db_path).expanduser().resolve()
        self.collection_name = collection_name
        self._lock = RLock()

    @contextmanager
    def _database(self) -> Iterator[VectorDatabase | None]:
        with self._lock:
            if not self.db_path.exists():
                yield None
                return
            with VectorDatabase(self.db_path) as db:
                yield db if db.client.collection_exists(self.collection_name) else None

    def _records(
        self,
        db: VectorDatabase,
        query_filter: models.Filter | None = None,
        fields: tuple[str, ...] = _PUBLIC_FIELDS,
    ) -> Iterator[Any]:
        cursor = None
        while True:
            points, cursor = db.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=query_filter,
                limit=256,
                offset=cursor,
                with_payload=list(fields),
                with_vectors=False,
            )
            yield from points
            if cursor is None:
                return

    def search(
        self,
        text: str,
        limit: int = 5,
        source: str | None = None,
        min_score: float | None = None,
    ) -> list[dict[str, Any]]:
        """语义搜索，按 Cosine 得分降序返回；只为当前问题生成一次向量。"""
        _text(text, "text")
        _pagination(limit)
        query_filter = _filter(source=source)
        if min_score is not None and (
            type(min_score) not in (int, float)
            or not math.isfinite(min_score)
            or not -1 <= min_score <= 1
        ):
            raise ValueError("min_score 必须是 -1 到 1 之间的有限数值")
        with self._database() as db:
            if db is None or db.client.count(self.collection_name, count_filter=query_filter).count == 0:
                return []
            db.check_embedding_model(self.collection_name, ollama.MODEL)
            query_text = (
                "Instruct: Given a web search query, retrieve relevant passages "
                "that answer the query\n"
                f"Query: {text}"
            )
            vector = ollama.embed_text(query_text)
            points = db.client.query_points(
                collection_name=self.collection_name,
                query=vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=list(_PUBLIC_FIELDS),
                with_vectors=False,
            ).points
            # 在 Python 中使用包含端点的比较，避免后端阈值语义排除恰好等于阈值的结果。
            return [
                {**_public(point), "score": point.score}
                for point in points
                if min_score is None or point.score >= min_score
            ]

    def keyword_search(
        self, text: str, limit: int = 20, offset: int = 0, source: str | None = None
    ) -> dict[str, Any]:
        """标题/正文不区分大小写的子串匹配；按 Point ID 分页，不按相关度排名。"""
        _text(text, "text")
        _pagination(limit, offset)
        query_filter = _filter(source=source)
        needle = text.casefold()
        matches: list[dict[str, Any]] = []
        skipped = 0
        with self._database() as db:
            if db is not None:
                for point in self._records(db, query_filter):
                    payload = point.payload or {}
                    body = str(payload.get("text", ""))
                    heading = " > ".join(str(part) for part in payload.get("heading_path", []))
                    if needle not in f"{heading}\n{body}".casefold():
                        continue
                    if skipped < offset:
                        skipped += 1
                        continue
                    matches.append(_public(point))
                    if len(matches) > limit:
                        break
        return {
            "items": matches[:limit], "offset": offset, "limit": limit,
            "has_more": len(matches) > limit,
        }

    def _document_summaries(self, db: VectorDatabase) -> list[dict[str, Any]]:
        groups: dict[tuple[str, str | None, str | None], list[dict[str, Any]]] = defaultdict(list)
        for point in self._records(db, fields=_STATE_FIELDS):
            payload = point.payload or {}
            source = payload.get("source")
            if isinstance(source, str):
                key = payload.get("processing_key")
                ingestion = payload.get("ingestion_id")
                groups[(source, key if isinstance(key, str) else None,
                        ingestion if isinstance(ingestion, str) else None)].append(payload)
        result = []
        for (source, key, ingestion), payloads in groups.items():
            counts = {p.get("chunk_count") for p in payloads if type(p.get("chunk_count")) is int}
            result.append({
                "source": source,
                "processing_key": key,
                "ingestion_id": ingestion,
                "stored_chunks": len(payloads),
                "expected_chunks": next(iter(counts)) if len(counts) == 1 else None,
                "complete": bool(stored_processing_keys(payloads)) if key and ingestion else None,
            })
        return sorted(result, key=lambda item: (
            item["source"], item["processing_key"] or "", item["ingestion_id"] or "",
        ))

    def list_documents(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """列出按来源、处理标识和写入批次分组的文档条目，包括旧版本和未完成写入。"""
        _pagination(limit, offset)
        with self._database() as db:
            documents = self._document_summaries(db) if db is not None else []
        return _page(documents, limit, offset)

    def get_document(
        self,
        source: str,
        processing_key: str | None = None,
        ingestion_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """读取已入库片段而非原始文件；未指定版本/批次时返回该来源的所有版本。"""
        _text(source, "source")
        _pagination(limit, offset)
        query_filter = _filter(source=source, processing_key=processing_key, ingestion_id=ingestion_id)
        with self._database() as db:
            chunks = [_public(point) for point in self._records(db, query_filter)] if db else []
        chunks.sort(key=lambda chunk: (
            chunk.get("processing_key", ""), chunk.get("ingestion_id", ""),
            chunk.get("start_index", 0), chunk.get("end_index", 0), chunk["id"],
        ))
        return {"source": source, **_page(chunks, limit, offset)}

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        """按检索返回的 Point ID 读取单个片段，支持 UUID 和历史非负整数 ID。"""
        _text(chunk_id, "chunk_id")
        if chunk_id.isascii() and chunk_id.isdecimal():
            point_id: str | int = int(chunk_id)
            if point_id >= 2**64:
                raise ValueError("整数 chunk_id 超出 uint64 范围")
        else:
            try:
                point_id = str(UUID(chunk_id))
            except ValueError as exc:
                raise ValueError("chunk_id 必须是 UUID 或非负整数") from exc
        with self._database() as db:
            if db is None:
                return None
            points = db.client.retrieve(
                self.collection_name, ids=[point_id], with_payload=list(_PUBLIC_FIELDS), with_vectors=False
            )
            return _public(points[0]) if points else None

    def stats(self) -> dict[str, Any]:
        """返回集合、模型、维度、片段数量及文档条目完整性；不调用模型。"""
        result = {
            "db_path": str(self.db_path), "collection_name": self.collection_name,
            "exists": False, "chunk_count": 0, "source_count": 0,
            "document_count": 0, "complete_document_count": 0,
            "embedding_model": None, "vector_size": None,
        }
        with self._database() as db:
            if db is None:
                return result
            info = db.client.get_collection(self.collection_name)
            documents = self._document_summaries(db)
            vectors = info.config.params.vectors
            result.update(
                exists=True,
                chunk_count=db.client.count(self.collection_name, exact=True).count,
                source_count=len({document["source"] for document in documents}),
                document_count=len(documents),
                complete_document_count=sum(document["complete"] is True for document in documents),
                embedding_model=(info.config.metadata or {}).get("embedding_model"),
                vector_size=vectors.size if isinstance(vectors, models.VectorParams) else None,
            )
        return result
