"""分批读取 T2Retrieval Parquet，保留原始 ID 以关联标准标注。"""

import hashlib
import math
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


@dataclass(frozen=True)
class TextRecord:
    id: str
    text: str


@dataclass(frozen=True)
class Judgment:
    query_id: str
    document_id: str
    score: float


@dataclass(frozen=True)
class RetrievalExample:
    """一道问题及其全部正相关标注；documents 按 ID 去重。"""

    query: TextRecord
    documents: list[TextRecord]
    judgments: list[Judgment]


def _one_file(root: Path, pattern: str) -> Path:
    files = sorted(root.glob(pattern))
    if not files:
        raise FileNotFoundError(f"{root} 下未找到 {pattern}")
    if len(files) != 1:
        raise ValueError(f"{pattern} 匹配到 {len(files)} 个文件，请只保留一个版本")
    return files[0]


def _identifier(value: Any, name: str) -> str:
    if type(value) not in (str, int) or not str(value).strip():
        raise ValueError(f"{name} 必须是非空字符串或整数 ID")
    return str(value)


def _rows(path: Path, columns: list[str], batch_size: int) -> Iterator[dict[str, Any]]:
    if type(batch_size) is not int or batch_size <= 0:
        raise ValueError("batch_size 必须是正整数")
    with pq.ParquetFile(path) as parquet:
        for batch in parquet.iter_batches(batch_size=batch_size, columns=columns):
            yield from batch.to_pylist()


def _text_records(path: Path, batch_size: int) -> Iterator[TextRecord]:
    for row in _rows(path, ["id", "text"], batch_size):
        record_id = _identifier(row["id"], f"{path.name}: id")
        text = row["text"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{path.name}: {record_id} 的 text 必须是非空字符串")
        yield TextRecord(record_id, text)


def _index_records(
    records: Iterator[TextRecord], required_ids: set[str], name: str, id_field: str,
) -> dict[str, TextRecord]:
    index: dict[str, TextRecord] = {}
    for record in records:
        if record.id not in required_ids:
            continue
        if record.id in index:
            raise ValueError(f"{name} 中存在重复 ID：{record.id}")
        index[record.id] = record
    missing = required_ids - index.keys()
    if missing:
        raise ValueError(f"标注中的 {id_field}={sorted(missing)[0]} 在 {name} 中不存在")
    return index


class T2Retrieval:
    """只读数据集入口，不构建向量、不访问知识库。

    当前支持各一个 corpus-*.parquet、queries-*.parquet、dev-*.parquet。
    构造时检查文件和列；逐行值在读取时校验。ID 统一为字符串，正文不清洗。
    """

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.corpus_path = _one_file(self.data_dir, "corpus-*.parquet")
        self.queries_path = _one_file(self.data_dir, "queries-*.parquet")
        self.qrels_path = _one_file(self.data_dir, "dev-*.parquet")
        self.counts: dict[str, int] = {}

        for name, path, required in (
            ("corpus", self.corpus_path, {"id", "text"}),
            ("queries", self.queries_path, {"id", "text"}),
            ("qrels", self.qrels_path, {"qid", "pid", "score"}),
        ):
            with pq.ParquetFile(path) as parquet:
                missing = required - set(parquet.schema_arrow.names)
                if missing:
                    raise ValueError(f"{path.name} 缺少字段：{', '.join(sorted(missing))}")
                self.counts[name] = parquet.metadata.num_rows

        # 仅对大小相同的可疑文件计算指纹，避免每次都扫描正常的大文件。
        if self.corpus_path.stat().st_size == self.queries_path.stat().st_size:
            with self.corpus_path.open("rb") as corpus, self.queries_path.open("rb") as queries:
                if hashlib.file_digest(corpus, "sha256").digest() == hashlib.file_digest(queries, "sha256").digest():
                    raise ValueError("corpus 与 queries 内容完全相同，可能重复下载，请检查文件")

    def iter_corpus(self, batch_size: int = 1000) -> Iterator[TextRecord]:
        return _text_records(self.corpus_path, batch_size)

    def iter_queries(self, batch_size: int = 1000) -> Iterator[TextRecord]:
        return _text_records(self.queries_path, batch_size)

    def iter_qrels(self, batch_size: int = 1000) -> Iterator[Judgment]:
        """保留全部标注和原始分值；score > 0 才作为相关资料。"""
        for row in _rows(self.qrels_path, ["qid", "pid", "score"], batch_size):
            if type(row["score"]) not in (int, float, str):
                raise ValueError("score 必须是有限数值")
            try:
                score = float(row["score"])
            except ValueError as exc:
                raise ValueError("score 必须是有限数值") from exc
            if not math.isfinite(score):
                raise ValueError("score 必须是有限数值")
            yield Judgment(
                _identifier(row["qid"], "qid"),
                _identifier(row["pid"], "pid"),
                score,
            )

    def iter_examples(
        self, *, limit: int | None = None, batch_size: int = 1000,
    ) -> Iterator[RetrievalExample]:
        """按 query 分组，逐个返回包含全部正相关资料的样本。

        顺序按 qid 首次出现在正相关标注中的位置；limit 限制问题数，不截断标注。
        每个文件最多扫描一遍，首次迭代时建立所选问题和资料的内存索引，然后 yield。
        这不是常量内存流式关联：全量使用时索引也可能很大，建议先设置 limit。
        """
        if limit is not None and (type(limit) is not int or limit <= 0):
            raise ValueError("limit 必须是正整数或 None")
        grouped: dict[str, list[Judgment]] = {}
        for judgment in self.iter_qrels(batch_size):
            if judgment.score <= 0:
                continue
            if judgment.query_id not in grouped:
                if limit is not None and len(grouped) >= limit:
                    continue
                grouped[judgment.query_id] = []
            grouped[judgment.query_id].append(judgment)
        if not grouped:
            return

        queries = _index_records(self.iter_queries(batch_size), set(grouped), "queries", "qid")
        document_ids = {item.document_id for judgments in grouped.values() for item in judgments}
        documents = _index_records(self.iter_corpus(batch_size), document_ids, "corpus", "pid")

        for query_id, judgments in grouped.items():
            # 保留标注顺序；同一篇资料可能重复标注，但正文只放一份。
            unique_ids = dict.fromkeys(item.document_id for item in judgments)
            yield RetrievalExample(
                query=queries[query_id],
                documents=[documents[document_id] for document_id in unique_ids],
                judgments=judgments,
            )

    def first_example(self, batch_size: int = 1000) -> RetrievalExample:
        """预览第一道有正相关标注的问题，包含它的全部相关资料。"""
        example = next(self.iter_examples(limit=1, batch_size=batch_size), None)
        if example is None:
            raise ValueError("没有 score > 0 的相关性标注")
        return example
