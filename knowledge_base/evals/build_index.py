"""使用 src 的通用 Parquet 切分入口，构建独立 T2Retrieval 评估集合。"""

import argparse
import hashlib
from itertools import batched
from pathlib import Path

from rag_mcp.chunk import iter_parquet_chunks
from rag_mcp.embed import Embed, Embeder, ollama
from rag_mcp.vector_databbase import VectorDatabase

from .datasets import T2Retrieval

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_COLLECTION = "t2retrieval_qwen3_baseline"
DEFAULT_EVAL_CHUNK_SIZE = 1024
INDEXING = "chunked_documents_v1"


def build_index(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    *,
    db_path: str | Path | None = None,
    collection_name: str = DEFAULT_COLLECTION,
    batch_size: int = 32,
    max_documents: int | None = None,
    chunk_size: int = DEFAULT_EVAL_CHUNK_SIZE,
) -> int:
    """正文先切分再分批向量化，返回写入的片段数，source 保存原始资料 ID。

    max_documents 限制 corpus 原始资料数，不限制片段数；chunk_size 单位为字符。
    不追加、不覆盖已有集合。重开数据库验证片段和文档数量后才标记构建完成。
    失败保留未完成集合，不自动清理或续传。MD/TXT 的 Fliter 流程不参与此构建。
    """
    for name, value in (("batch_size", batch_size), ("chunk_size", chunk_size)):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} 必须是正整数")
    if max_documents is not None and (type(max_documents) is not int or max_documents <= 0):
        raise ValueError("max_documents 必须是正整数或 None")
    if not isinstance(collection_name, str) or not collection_name.strip():
        raise ValueError("collection_name 不能为空")

    dataset = T2Retrieval(data_dir)
    storage = Path(db_path).expanduser().resolve() if db_path is not None else dataset.data_dir / "storage"
    expected_documents = dataset.counts["corpus"]
    if max_documents is not None:
        expected_documents = min(expected_documents, max_documents)
    if expected_documents == 0:
        print("corpus 为空，跳过切分、向量化和数据库写入", flush=True)
        return 0

    chunks = iter_parquet_chunks(
        dataset.corpus_path, chunk_size=chunk_size, batch_size=batch_size, max_documents=max_documents,
    )
    written = 0
    sources: set[str] = set()
    vector_size: int | None = None
    embeder = Embeder()
    with VectorDatabase(storage) as db:
        if db.client.collection_exists(collection_name):
            raise ValueError(f"集合 {collection_name} 已存在，请换一个新集合名；不会追加或覆盖数据")
        with dataset.corpus_path.open("rb") as stream:
            corpus_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        metadata = {
            "embedding_model": ollama.MODEL,
            "dataset": "t2retrieval",
            "indexing": INDEXING,
            "source_kind": "corpus_document_id",
            "corpus_sha256": corpus_hash,
            "document_count": expected_documents,
            "chunk_count": 0,
            "chunk_size": chunk_size,
            "chunk_unit": "characters",
            "chunker": "recursive_text_v1",
            "build_complete": False,
        }
        print(f"将切分并向量化 {expected_documents} 篇资料；每片最多 {chunk_size} 个字符", flush=True)
        print(f"模型：{ollama.MODEL}；存储目录：{storage}；集合：{collection_name}", flush=True)
        for batch in batched(chunks, batch_size):
            embeds: list[Embed] = []
            for chunk in batch:
                try:
                    embeds.append(embeder.embed(chunk))
                except Exception as exc:
                    location = chunk.metadata
                    raise RuntimeError(
                        f"资料 ID={location.source} 字符范围 [{location.start_index}:{location.end_index}] 向量化失败"
                    ) from exc
            current_size = len(embeds[0].vector)
            if current_size == 0 or any(len(item.vector) != current_size for item in embeds):
                raise ValueError("本批向量维度不一致或为空")
            if vector_size is None:
                vector_size = current_size
                db.create_collection(collection_name, vector_size, embedding_model=ollama.MODEL)
                db.client.update_collection(collection_name, metadata=metadata)
            elif current_size != vector_size:
                raise ValueError(f"向量维度发生变化：预期 {vector_size}，实际 {current_size}")
            db.upsert(collection_name, embeds)
            sources.update(chunk.metadata.source for chunk in batch)
            written += len(embeds)
            print(f"已写入 {written} 个片段，涉及 {len(sources)}/{expected_documents} 篇资料", flush=True)

    with VectorDatabase(storage) as db:
        total = db.client.count(collection_name, exact=True).count
        if total != written or len(sources) != expected_documents:
            raise RuntimeError(
                f"持久化记录数不符：预期 {expected_documents} 篇资料/{written} 个片段，"
                f"实际处理 {len(sources)} 篇资料/存储 {total} 个片段"
            )
        db.client.update_collection(
            collection_name, metadata={**metadata, "chunk_count": total, "build_complete": True},
        )
    print(f"构建完成并验证持久化：{len(sources)} 篇资料，{written} 个片段", flush=True)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="切分 T2Retrieval corpus 并向量化到独立评估集合")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="原始 Parquet 目录")
    parser.add_argument("--db-path", type=Path, help="默认使用 data-dir/storage")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="必须是尚不存在的新集合")
    parser.add_argument("--batch-size", type=int, default=32, help="读取批大小和每批写入片段数，非模型并发数")
    parser.add_argument("--max-documents", type=int, help="仅导入 corpus 前 N 篇资料，不限制片段数")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_EVAL_CHUNK_SIZE, help="每个片段最大字符数，默认 1024")
    args = parser.parse_args()
    build_index(
        args.data_dir, db_path=args.db_path, collection_name=args.collection,
        batch_size=args.batch_size, max_documents=args.max_documents, chunk_size=args.chunk_size,
    )


if __name__ == "__main__":
    main()
