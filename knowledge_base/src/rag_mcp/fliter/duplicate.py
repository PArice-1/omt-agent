"""切分前按文件原始内容和处理配置精确去重。"""

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .schema import FileSelection, ProcessingProfile

suffixs = (".md", ".txt")


def file_processing_key(file: Path, profile: ProcessingProfile) -> str:
    """流式读取原始字节计算标识；路径不参与，解析器类型参与。"""
    suffix = file.suffix.lower()
    if suffix not in suffixs:
        raise ValueError(f"不支持的文件后缀：{suffix}，目前支持 .md 和 .txt")
    with file.open("rb") as stream:
        content_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    content = {"content_hash": content_hash, "parser": suffix, **asdict(profile)}
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:file-v1:" + hashlib.sha256(encoded).hexdigest()


def stored_processing_keys(payloads: Iterable[Mapping[str, Any]]) -> set[str]:
    """只接受单次写入中编号完整的文件；旧记录无法还原原始文件哈希。

    按来源、处理标识、写入批次和预期片段数分组，避免不同副本或多次
    不完整写入被拼成完整文档。重复编号不会增加完成度。
    """
    documents: dict[tuple[str, str, str, int], set[int]] = defaultdict(set)
    for payload in payloads:
        source = payload.get("source")
        key = payload.get("processing_key")
        ingestion_id = payload.get("ingestion_id")
        index, count = payload.get("chunk_index"), payload.get("chunk_count")
        if (
            isinstance(source, str)
            and isinstance(key, str)
            and key.startswith("sha256:file-v1:")
            and isinstance(ingestion_id, str)
            and ingestion_id
            and type(index) is int
            and type(count) is int
            and 0 <= index < count
        ):
            documents[(source, key, ingestion_id, count)].add(index)
    # 每个编号已经验证在 [0, count) 内，唯一编号数等于 count 即完整。
    return {
        key
        for (_, key, _, count), indices in documents.items()
        if len(indices) == count
    }


def remove_duplicates(selection: FileSelection, stored_keys: set[str]) -> FileSelection:
    """保持输入顺序保留第一份文件，不修改输入或持久化处理标识。"""
    seen = set(stored_keys)
    files: list[Path] = []
    keys: dict[str, str] = {}
    for file in selection.files:
        source = str(file)
        key = selection.processing_keys[source]
        if key not in seen:
            seen.add(key)
            files.append(file)
            keys[source] = key
    return FileSelection(files, keys)
