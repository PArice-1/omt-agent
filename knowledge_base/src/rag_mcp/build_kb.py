"""串联切分、向量化和 Qdrant 写入，验证本地知识库的持久化结果。"""

import argparse
from pathlib import Path

from .chunk import Chunker, search_files
from .chunk.rules import DEFAULT_CHUNK_SIZE
from .config import DEFAULT_COLLECTION, DEFAULT_DB_PATH
from .embed import Embeder, ollama
from .fliter import Fliter, ProcessingProfile
from .vector_databbase import VectorDatabase


def _discover_files[PathType: str | Path](paths: list[PathType], db_path: Path) -> list[Path]:
    if not isinstance(paths, list) or any(not isinstance(path, (str, Path)) for path in paths):
        raise TypeError("paths 必须是 list[str | Path]")
    roots: list[Path] = []
    files: set[Path] = set()
    for path in paths:
        resolved = Path(path).expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(resolved)
        if resolved.is_dir():
            roots.append(resolved)
        elif resolved.is_file():
            if resolved.suffix.lower() not in (".md", ".txt"):
                raise ValueError(f"不支持的文件类型：{resolved.suffix}")
            files.add(resolved)
        else:
            raise ValueError(f"不是普通文件或目录：{resolved}")
    files.update(search_files(roots))
    return sorted(file for file in files if not file.is_relative_to(db_path))


def build_kb[PathType: str | Path](
    paths: list[PathType],
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    collection_name: str = DEFAULT_COLLECTION,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> int:
    """将多个目录/文件中的 MD/TXT 追加到同一知识库，返回本次写入片段数。

    目录递归扫描；重叠目录和重复路径合并，排除 db_path 下的文件。
    所有路径相对于当前工作目录，存储位置不随输入目录改变。
    切分前过滤已入库及本批次重复文件；新版本追加，保留已有记录。
    构建期间源文件必须保持不变，不能同时运行本地 MCP 服务或其他构建进程。
    处理错误直接向上传递，部分写入重试不自动清理残留记录。
    """
    if not isinstance(collection_name, str) or not collection_name.strip():
        raise ValueError("collection_name 不能为空")
    chunker = Chunker(chunk_size=chunk_size)
    db_path = Path(db_path).expanduser().resolve()
    files = _discover_files(paths, db_path)
    print(f"发现 {len(files)} 个 MD/TXT 文件", flush=True)

    profile = ProcessingProfile(chunk_size=chunker.chunk_size, embedding_model=ollama.MODEL)
    if db_path.exists():
        with VectorDatabase(db_path=db_path) as db:
            if db.client.collection_exists(collection_name):
                db.check_embedding_model(collection_name, ollama.MODEL)
            selection = Fliter(db, collection_name, profile=profile).filter(files)
    else:
        selection = Fliter(profile=profile).filter(files)
    print(
        f"去重后保留 {len(selection.files)} 个文件，过滤 {len(files) - len(selection.files)} 个",
        flush=True,
    )
    if not selection.files:
        print("没有待处理文件，跳过切分、向量化和数据库写入", flush=True)
        return 0

    chunks = chunker.chunk(selection.files)
    print(f"切分得到 {len(chunks)} 个片段", flush=True)
    if not chunks:
        print("没有可入库的正文，跳过向量化和数据库写入", flush=True)
        return 0

    print("正在调用 Ollama 生成向量……", flush=True)
    embeds = Embeder().embed(chunks)
    vector_size = len(embeds[0].vector)
    print(f"已生成 {len(embeds)} 个 {vector_size} 维向量", flush=True)

    with VectorDatabase(db_path=db_path) as db:
        if not db.client.collection_exists(collection_name):
            db.create_collection(
                collection_name, vector_size=vector_size, embedding_model=ollama.MODEL
            )
        before = db.client.count(collection_name, exact=True).count
        point_ids = db.upsert(collection_name, embeds, processing_keys=selection.processing_keys)

    # 关闭后重新打开，确认数据已经持久保存，而非只存在于当前客户端内存中。
    with VectorDatabase(db_path=db_path) as db:
        total = db.client.count(collection_name, exact=True).count
        if total != before + len(point_ids):
            raise RuntimeError("持久化验证失败：数据库记录数与预期不符")
        sample = db.client.retrieve(
            collection_name, ids=point_ids[:1], with_payload=True
        )
        if not sample or sample[0].payload is None:
            raise RuntimeError("持久化验证失败：无法读取已写入的片段")
        if sample[0].payload.get("text") != embeds[0].metadata.text:
            raise RuntimeError("持久化验证失败：片段正文与输入不符")

    print(f"持久化验证通过：本次写入 {len(point_ids)} 条，集合共 {total} 条", flush=True)
    print(f"数据库位置：{db_path}", flush=True)
    return len(point_ids)


def main() -> None:
    parser = argparse.ArgumentParser(description="将多个目录或 MD/TXT 文件构建为持久化知识库")
    parser.add_argument("paths", nargs="+", help="目录或文件路径，可混合传入")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Qdrant 存储目录")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="集合名称")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE, help="切分最大字符数")
    args = parser.parse_args()
    build_kb(
        args.paths,
        db_path=args.db_path,
        collection_name=args.collection,
        chunk_size=args.chunk_size,
    )


if __name__ == "__main__":
    main()
