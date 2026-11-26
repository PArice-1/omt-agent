"""复用已有向量报告的问题、标注和数据库片段，导出 BM25 公平对照报告。"""

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory
from typing import Any

import jieba

from rag_mcp.vector_databbase import VectorDatabase

from .bm25 import BM25Index, SearchChunk
from .datasets import Judgment, RetrievalExample, TextRecord
from .metrics import score_query

DEFAULT_STORAGE = Path(__file__).resolve().parent / "data" / "storage"
DEFAULT_RESULTS = Path(__file__).resolve().parent / "results"
METRICS = ("hit_at_k", "recall_at_k", "mrr_at_k")


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _baseline(content: bytes) -> dict[str, Any]:
    """解析并验证已读取的向量报告字节，不重新筛选问题或截断正相关标注。"""
    report = json.loads(content)
    if not isinstance(report, dict) or report.get("status") not in ("completed", "no_eligible_queries"):
        raise ValueError("需要已完成的 evals.run JSON 报告")
    config = report.get("config")
    if not isinstance(config, dict) or not isinstance(report.get("selection"), dict):
        raise ValueError("向量报告缺少配置或问题选择信息")
    if not _identifier(report.get("created_at")) or not _identifier(config.get("embedding_model")):
        raise ValueError("向量报告缺少时间或模型信息")
    for name in ("candidate_documents", "candidate_chunks"):
        if type(config.get(name)) is not int or config[name] <= 0:
            raise ValueError(f"向量报告 {name} 必须为正整数")
    for name in ("selection_policy", "scope"):
        if not _identifier(config.get(name)):
            raise ValueError(f"向量报告缺少 {name}")
    for name in ("k", "fetch_k"):
        if type(config.get(name)) is not int or not 1 <= config[name] <= 100:
            raise ValueError(f"向量报告 {name} 必须在 1 到 100 之间")
    if config["fetch_k"] < config["k"]:
        raise ValueError("向量报告 fetch_k 不能小于 k")
    if config.get("ranking_policy") != "bounded_chunk_search;first_source_occurrence;document_top_k":
        raise ValueError("向量报告的排名口径不受支持")
    if not _identifier(config.get("collection")) or not isinstance(config.get("collection_metadata"), dict):
        raise ValueError("向量报告缺少集合或构建元数据")
    results = report.get("results")
    if not isinstance(results, list) or report.get("selection", {}).get("evaluated_queries") != len(results):
        raise ValueError("向量报告的实际题数与单题明细不一致")
    if (report["status"] == "completed") != bool(results):
        raise ValueError("向量报告状态与单题明细不一致")
    seen = set()
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("向量报告单题明细必须是对象")
        query_id = result.get("query_id")
        expected = result.get("expected_document_ids")
        retrieved = result.get("retrieved_document_ids")
        if not _identifier(query_id) or query_id in seen or not _identifier(result.get("query")):
            raise ValueError("向量报告的问题 ID 重复、缺失或问题正文无效")
        seen.add(query_id)
        if not isinstance(expected, list) or not expected or not all(_identifier(item) for item in expected):
            raise ValueError(f"问题 {query_id} 缺少完整正相关资料 ID")
        if (not isinstance(retrieved, list) or not all(_identifier(item) for item in retrieved)
                or len(retrieved) > config["k"] or len(set(retrieved)) != len(retrieved)):
            raise ValueError(f"问题 {query_id} 的向量文档排名无效")
        hits = result.get("retrieved_chunks")
        if not isinstance(hits, list) or len(hits) > config["fetch_k"]:
            raise ValueError(f"问题 {query_id} 的向量片段预算无效")
        if any(not isinstance(hit, dict) or not _identifier(hit.get("chunk_id"))
               or not _identifier(hit.get("document_id")) for hit in hits):
            raise ValueError(f"问题 {query_id} 的向量片段 ID 或来源无效")
        document_ids = list(dict.fromkeys(hit["document_id"] for hit in hits))[:config["k"]]
        if document_ids != retrieved:
            raise ValueError(f"问题 {query_id} 的向量片段与文档排名不一致")
    return report


def _chunks(storage: Path, baseline: dict[str, Any]) -> list[SearchChunk]:
    """在临时副本中读取全部候选片段，防止 Qdrant 打开/关闭改变原展示快照。

    storage 必须是静止的本地 Qdrant 目录，运行期间不得有其他进程写入。
    复制整个目录需要同等临时磁盘空间；只读取 payload，不加载向量到 BM25。
    验证完成标记、构建元数据、计数及基线曾返回片段的身份，失败即停止。
    """
    if not storage.is_dir() or not (storage / "meta.json").is_file():
        raise FileNotFoundError(f"本地 Qdrant 数据库不存在或不完整：{storage}")
    config = baseline["config"]
    collection = config["collection"]
    chunks = []
    with TemporaryDirectory(prefix="bm25-snapshot-") as temporary:
        copied = Path(temporary) / "storage"
        shutil.copytree(storage, copied, ignore=shutil.ignore_patterns(".lock"))
        with VectorDatabase(copied) as db:
            if not db.client.collection_exists(collection):
                raise ValueError(f"集合不存在：{collection}")
            metadata = db.client.get_collection(collection).config.metadata or {}
            if metadata.get("build_complete") is not True:
                raise ValueError("候选集合未构建完成")
            if metadata != config["collection_metadata"]:
                raise ValueError("候选集合构建元数据与向量报告不一致")
            cursor = None
            while True:
                points, cursor = db.client.scroll(
                    collection, limit=256, offset=cursor, with_payload=["source", "text"], with_vectors=False,
                )
                for point in points:
                    payload = point.payload or {}
                    if not _identifier(payload.get("source")) or not _identifier(payload.get("text")):
                        raise ValueError(f"片段 {point.id} 缺少有效 source 或正文")
                    chunks.append(SearchChunk(str(point.id), payload["source"], payload["text"]))
                if cursor is None:
                    break
    sources = {chunk.source for chunk in chunks}
    if not chunks or len(chunks) != config["candidate_chunks"] or len(sources) != config["candidate_documents"]:
        raise ValueError("候选片段或文档数与向量报告不一致")
    identities = {chunk.id: chunk.source for chunk in chunks}
    if len(identities) != len(chunks):
        raise ValueError("候选片段 ID 重复")
    for result in baseline["results"]:
        if not set(result["expected_document_ids"]).issubset(sources):
            raise ValueError(f"问题 {result['query_id']} 的正相关资料未被候选库完整覆盖")
        if any(identities.get(hit["chunk_id"]) != hit["document_id"] for hit in result["retrieved_chunks"]):
            raise ValueError(f"问题 {result['query_id']} 的向量片段与当前候选库不一致")
    return sorted(chunks, key=lambda chunk: chunk.id)


def _markdown(report: dict[str, Any]) -> str:
    """生成含参数、平均对照和逐题指标的中文报告；原始排名保留在同名 JSON。"""
    config = report["config"]
    lines = [
        "# BM25 与向量检索对照报告", "",
        f"- 时间：{report['created_at']}",
        f"- 向量基线：`{report['vector_baseline']['path']}`",
        f"- 向量模型 / 集合：`{report['vector_baseline']['embedding_model']}` / `{config['collection']}`",
        f"- 候选资料：{config['candidate_documents']} 篇；候选片段：{config['candidate_chunks']} 个",
        f"- 评估问题：{report['selection']['evaluated_queries']} 道；与基线完全相同",
        f"- 文档 K={config['k']}；片段预算 fetch_k={config['fetch_k']}",
        f"- BM25：k1={config['k1']}，b={config['b']}；分词器 jieba {config['jieba_version']}",
        "- 预处理：统一小写、精确分词、HMM=False、去除纯符号；不删除停用词。",
        "- IDF：ln(1 + (N - df + 0.5) / (df + 0.5))；长度按片段分词后的词数。",
        "- BM25 只返回正分匹配；无匹配不补零分结果；平分按片段 ID 升序。", "",
        "> 两边均在固定片段预算内按 source 首次出现去重，取前 K 篇；不足 K 篇不补齐。",
        "> 复用基线已选择的问题及完整正相关 ID，不用答案 ID 过滤搜索，不重新请求 embedding。",
        "> 向量结果为历史报告中的排名，不是本次重新运行；本次不比较耗时。",
        "> 缩小候选库、按资料覆盖筛选问题会改变难度；不是完整 T2Retrieval 官方基准成绩。", "",
    ]
    if not report["results"]:
        return "\n".join(lines + ["## 未执行检索", "", "基线没有可评问题，指标为 null，而不是 0。", ""])
    lines += ["## 平均指标", "", "| 指标 | BM25 | 向量基线 | 差值（BM25 - 向量） |", "|---|---:|---:|---:|"]
    for metric in METRICS:
        lines.append(
            f"| {metric} | {report['summary'][metric]:.6f} | "
            f"{report['vector_summary'][metric]:.6f} | {report['delta'][metric]:+.6f} |"
        )
    lines += ["", "## 单题指标", "", "| query_id | BM25 Hit | BM25 Recall | BM25 RR | 向量 Hit | 向量 Recall | 向量 RR |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for item in report["results"]:
        query_id = item["query_id"].replace("|", "\\|").replace("\n", " ").replace("\r", " ")
        values = [item[key][metric] for key in ("metrics", "vector_metrics") for metric in METRICS]
        lines.append(f"| {query_id} | " + " | ".join(f"{value:.4f}" for value in values) + " |")
    lines += ["", "每道题等权平均。问题正文、全部相关 ID、片段排名、文档排名及 BM25 分数见同名 JSON。",
              "BM25 分数与向量相似度不是同一量纲，不直接比较分数。", ""]
    return "\n".join(lines)


def run_bm25_evaluation(
    baseline_report: str | Path,
    *,
    db_path: str | Path = DEFAULT_STORAGE,
    k1: float = 1.2,
    b: float = 0.75,
    output: str | Path | None = None,
) -> dict[str, Any]:
    """复用 evals.run 的全部已评问题，运行真实 BM25 并导出 JSON/Markdown 对照。

    baseline_report 指向已有向量 JSON 明细，必须含完整正相关 ID 和片段排名。
    db_path 指向其对应的本地静止数据库；仅在临时副本打开，不写原库。
    k、fetch_k、候选资料和问题集合完全继承基线，不另行筛选或调节。
    k1/b 的范围、默认值见 BM25Index；output 为 .json，附带同名 .md，
    默认在 evals/results/ 下按 UTC 时间命名，任何同名文件存在都拒绝覆盖。
    基线无可评问题时导出 null 指标；读取、校验或检索异常不生成完成报告。
    """
    BM25Index.validate_parameters(k1, b)
    created_at = datetime.now(timezone.utc)
    json_path = (Path(output).expanduser().resolve() if output is not None
                 else DEFAULT_RESULTS / f"bm25-{created_at:%Y%m%dT%H%M%S%fZ}.json")
    if json_path.suffix != ".json":
        raise ValueError("output 必须使用 .json 扩展名，同时生成同名 .md 报告")
    md_path = json_path.with_suffix(".md")
    if json_path.exists() or md_path.exists():
        raise FileExistsError("报告文件已存在，请选择新的 --output 路径，不会覆盖")
    baseline_path = Path(baseline_report).expanduser().resolve()
    # 对同一份字节计算指纹并解析，避免多次读取时报告发生变化。
    baseline_bytes = baseline_path.read_bytes()
    baseline = _baseline(baseline_bytes)
    storage = Path(db_path).expanduser().resolve()
    chunks = _chunks(storage, baseline)
    index = BM25Index(chunks, k1=k1, b=b)
    k, fetch_k = baseline["config"]["k"], baseline["config"]["fetch_k"]
    results = []
    for original in baseline["results"]:
        query_id = original["query_id"]
        example = RetrievalExample(
            TextRecord(query_id, original["query"]), [],
            [Judgment(query_id, document_id, 1.0) for document_id in original["expected_document_ids"]],
        )
        try:
            hits = index.search(example.query.text, limit=fetch_k)
        except Exception as exc:
            raise RuntimeError(f"问题 ID={query_id} BM25 检索失败，未生成完成报告") from exc
        documents = []
        seen: set[str] = set()
        for chunk_rank, hit in enumerate(hits, start=1):
            if hit["source"] in seen:
                continue
            seen.add(hit["source"])
            documents.append({"rank": len(documents) + 1, "document_id": hit["source"],
                              "score": hit["score"], "first_chunk_rank": chunk_rank})
            if len(documents) == k:
                break
        retrieved_ids = [item["document_id"] for item in documents]
        results.append({
            "query_id": query_id, "query": example.query.text,
            "expected_document_ids": original["expected_document_ids"],
            "retrieved_document_ids": retrieved_ids, "retrieved": documents,
            "retrieved_chunks": [
                {"rank": rank, "chunk_id": hit["id"], "document_id": hit["source"], "score": hit["score"]}
                for rank, hit in enumerate(hits, start=1)
            ],
            "fewer_than_k_documents": len(documents) < k,
            "metrics": score_query(example, retrieved_ids, k=k),
            "vector_retrieved_document_ids": original["retrieved_document_ids"],
            "vector_metrics": score_query(example, original["retrieved_document_ids"], k=k),
        })
    summary = {metric: mean(item["metrics"][metric] for item in results) if results else None for metric in METRICS}
    vector_summary = {metric: mean(item["vector_metrics"][metric] for item in results) if results else None for metric in METRICS}
    delta = {}
    for metric in METRICS:
        bm25_value, vector_value = summary[metric], vector_summary[metric]
        delta[metric] = bm25_value - vector_value if bm25_value is not None and vector_value is not None else None
    fingerprint = hashlib.sha256()
    for chunk in chunks:
        fingerprint.update((json.dumps([chunk.id, chunk.source, chunk.text], ensure_ascii=False) + "\n").encode())
    config = baseline["config"]
    report = {
        "created_at": created_at.isoformat(), "status": "completed" if results else "no_eligible_queries",
        "config": {
            **{key: config[key] for key in ("collection", "k", "fetch_k", "candidate_documents", "candidate_chunks",
                                            "ranking_policy", "selection_policy", "scope", "collection_metadata")},
            "retriever": "bm25", "db_path": str(storage), "k1": k1, "b": b,
            "idf": "ln(1+(N-df+0.5)/(df+0.5))", "jieba_version": jieba.__version__,
            "tokenizer": "jieba_precise;HMM=False;lowercase;drop_non_alnum;no_stopwords",
            "query_terms": "unique", "zero_match_policy": "return_empty;positive_scores_only",
            "tie_break": "chunk_id_ascending", "candidate_payload_sha256": fingerprint.hexdigest(),
        },
        "vector_baseline": {"path": str(baseline_path), "sha256": hashlib.sha256(baseline_bytes).hexdigest(),
                            "created_at": baseline["created_at"], "embedding_model": config["embedding_model"]},
        "selection": baseline["selection"], "summary": summary, "vector_summary": vector_summary,
        "delta": delta,
        "results": results,
    }
    json_text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    md_text = _markdown(report)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("x", encoding="utf-8") as stream:
        stream.write(json_text)
    with md_path.open("x", encoding="utf-8") as stream:
        stream.write(md_text)
    print(f"已评估 {len(results)} 道问题；BM25：{summary}", flush=True)
    print(f"JSON 明细：{json_path}\nMarkdown 对照报告：{md_path}", flush=True)
    return report


def main() -> None:
    """命令行只读取向量报告和数据库副本，默认使用当前项目的评估存储目录。"""
    parser = argparse.ArgumentParser(description="复用向量报告与候选片段，运行 BM25 并导出对照报告（不请求模型）")
    parser.add_argument("--baseline-report", type=Path, required=True, help="已有 evals.run 的 JSON 明细")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_STORAGE, help="与报告对应的静止本地 Qdrant 数据库")
    parser.add_argument("--k1", type=float, default=1.2, help="词频饱和参数，有限正数，默认 1.2")
    parser.add_argument("--b", type=float, default=0.75, help="长度归一化，范围 0 到 1，默认 0.75")
    parser.add_argument("--output", type=Path, help="JSON 路径，附带同名 Markdown；默认按时间命名，不覆盖")
    args = parser.parse_args()
    run_bm25_evaluation(args.baseline_report, db_path=args.db_path, k1=args.k1, b=args.b, output=args.output)


if __name__ == "__main__":
    main()
