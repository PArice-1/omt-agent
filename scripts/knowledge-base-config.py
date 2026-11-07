#!/usr/bin/env python3
"""生成 OMT_CLI_MCP_SERVERS / OMT_API_MCP_SERVERS 配置，不启动或写入知识库。"""

import argparse
import json
from pathlib import Path


class PluginArguments(argparse.Namespace):
    source: Path = Path.home() / ".omt" / "knowledge-database"
    db_path: Path | None = None
    collection: str = "knowledge"
    build_on_start: bool = False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--source", type=Path, default=Path.home() / ".omt" / "knowledge-database",
                        help="资料目录；路径仅写入配置，不会创建或扫描")
    _ = parser.add_argument("--db-path", type=Path, help="默认资料目录下的 storage；不同进程应指定不同目录")
    _ = parser.add_argument("--collection", default="knowledge", help="Qdrant 集合名")
    _ = parser.add_argument("--build-on-start", action="store_true", help="显式启用启动构建，可能请求 Ollama")
    args = parser.parse_args(namespace=PluginArguments())
    root = Path(__file__).resolve().parents[1]
    source = args.source.expanduser().resolve()
    db_path = (args.db_path or source / "storage").expanduser().resolve()
    command_args = ["--db-path", str(db_path), "--collection", args.collection]
    if args.build_on_start:
        command_args.extend(["--build-on-start", "--source", str(source)])
    print(json.dumps({"knowledge": {
        "transport": "stdio",
        "command": str(root / "scripts" / "start-knowledge-base.sh"),
        "args": command_args,
        "cwd": str(root / "knowledge_base"),
    }}, ensure_ascii=False))


if __name__ == "__main__":
    main()
