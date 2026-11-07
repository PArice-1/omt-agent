"""基于已构建的 Qdrant 知识库提供只读 MCP 工具。"""

import argparse
import os
from contextlib import redirect_stdout
from pathlib import Path

from mcp.server import MCPServer

from ..build_kb import build_kb
from ..chunk.rules import DEFAULT_CHUNK_SIZE
from ..config import DEFAULT_COLLECTION, DEFAULT_DB_PATH
from .tools import register_tools
from .knowledge_base import KnowledgeBase


def create_server(
    db_path: str | Path = DEFAULT_DB_PATH,
    collection_name: str = DEFAULT_COLLECTION,
) -> MCPServer:
    """创建工具注册表；不扫描源文件、不请求模型、不打开数据库。"""
    server = MCPServer("rag-mcp")
    register_tools(server, KnowledgeBase(db_path, collection_name))
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="通过 stdio 提供持久化知识库 MCP 工具")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Qdrant 存储目录")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="集合名称")
    parser.add_argument("--build-on-start", action="store_true", help="启动服务前增量构建知识库")
    parser.add_argument(
        "--source", nargs="+", help="构建源目录或 MD/TXT 文件，可混合传入；默认 ./knowledge-base",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
        help="启动构建的切分最大字符数",
    )
    args = parser.parse_args()
    if args.source is not None and not args.build_on_start:
        parser.error("--source 需要同时指定 --build-on-start")
    if args.build_on_start:
        # 丢弃构建进度输出；异常仍向外抛出，构建完成后才启动 MCP。
        with open(os.devnull, "w") as sink, redirect_stdout(sink):
            build_kb(
                args.source or ["./knowledge-base"],
                db_path=args.db_path,
                collection_name=args.collection,
                chunk_size=args.chunk_size,
            )
    create_server(args.db_path, args.collection).run(transport="stdio")


if __name__ == "__main__":
    main()
