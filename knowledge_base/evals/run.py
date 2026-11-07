"""批量检索 T2Retrieval，输出 JSON 明细和 Markdown 汇总报告。"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from rag_mcp.embed import ollama
from rag_mcp.mcp import KnowledgeBase
from rag_mcp.vector_databbase import VectorDatabase

from .build_index import DEFAULT_COLLECTION, DEFAULT_DATA_DIR, INDEXING
from .datasets import Judgment, RetrievalExample, T2Retrieval
from .metrics import score_query

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"
METRICS = ("hit_at_k", "recall_at_k", "mrr_at_k")


def _candidates(storage: Path, collection: str, dataset: T2Retrieval) -> tuple[set[str], dict[str, Any]]:
    if not storage.exists():
        raise FileNotFoundError(f"数据库目录不存在：{storage}")
    with VectorDatabase(storage) as db:
        if not db.client.collection_exists(collection):
            raise ValueError(f"集合不存在：{collection}")
        metadata = db.client.get_collection(collection).config.metadata or {}
        if metadata.get("build_complete") is not True:
            raise ValueError("集合尚未构建完成，不能用于评估")
        if metadata.get("embedding_model") != ollama.MODEL:
            raise ValueError("集合的 embedding 模型与当前模型不一致")
        indexing = metadata.get("indexing")
        if metadata.get("dataset") != "t2retrieval" or indexing not in (INDEXING, "one_record_one_vector"):
            raise ValueError("需要使用 evals.build_index 构建的 T2Retrieval 集合")
        with dataset.corpus_path.open("rb") as stream:
            corpus_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        if metadata.get("corpus_sha256") != corpus_hash:
            raise ValueError("corpus 文件与构建集合时的 SHA-256 不一致")
        sources: set[str] = set()
        cursor = None
        count = 0
        while True:
            points, cursor = db.client.scroll(
                collection, limit=256, offset=cursor, with_payload=["source"], with_vectors=False,
            )
            for point in points:
                source = (point.payload or {}).get("source")
                if not isinstance(source, str) or not source.strip():
                    raise ValueError("集合的 source 缺失或无效")
                if indexing == "one_record_one_vector" and source in sources:
                    raise ValueError("旧版一篇资料一个向量的集合不能包含重复 source")
                sources.add(source)
                count += 1
            if cursor is None:
                break
        expected_chunks = metadata.get("chunk_count") if indexing == INDEXING else metadata.get("document_count")
        if (not count or type(expected_chunks) is not int or count != expected_chunks
                or type(metadata.get("document_count")) is not int or len(sources) != metadata["document_count"]):
            raise ValueError("集合实际片段记录数或文档数与构建记录不一致或集合为空")
    return sources, metadata


def _markdown(report: dict[str, Any]) -> str:
    config = report["config"]
    selection = report["selection"]
    summary = report["summary"]
    lines = [
        "# T2Retrieval 检索评估报告", "",
        f"- 时间：{report['created_at']}",
        f"- 集合：`{config['collection']}`",
        f"- 模型：`{config['embedding_model']}`",
        f"- 候选资料数：{config['candidate_documents']} / {config['corpus_documents']}",
        f"- 候选片段数：{config['candidate_chunks']}",
        f"- 文档 Top-K：{config['k']}；检索片段上限：{config['fetch_k']}",
        f"- 有正相关标注的问题数：{selection['positive_queries']}",
        f"- 全部正相关资料在库中的问题数：{selection['eligible_queries']}",
        f"- 因资料不全而排除的问题数：{selection['excluded_incomplete_coverage']}",
        f"- 本次实际评估问题数：{selection['evaluated_queries']}", "",
        "> 只选择全部正相关资料在候选库中的问题；搜索不使用答案 ID 过滤。",
        "> 在固定片段检索预算内，按 source 首次出现的顺序去重，再取前 K 篇文档；不足 K 篇不补齐。",
        "> 缩小候选库和筛选问题会改变任务难度，本报告不是完整 T2Retrieval 官方基准成绩。", "",
    ]
    if report["status"] == "no_eligible_queries":
        lines += ["## 未执行检索", "", "没有满足完整资料覆盖条件的问题，未调用模型，指标为 null，而不是 0。",
                  "请扩大候选库，或重新准备包含全部相关资料及干扰资料的候选库。", ""]
    else:
        lines += ["## 平均指标", "", "| 指标 | 平均值 |", "|---|---:|"]
        lines += [f"| {key} | {summary[key]:.6f} |" for key in METRICS]
        lines += ["", "## 单题指标", "", "| query_id | Hit@K | Recall@K | RR@K |", "|---|---:|---:|---:|"]
        for result in report["results"]:
            query_id = result["query_id"].replace("|", "\\|").replace("\n", " ").replace("\r", " ")
            scores = result["metrics"]
            lines.append(f"| {query_id} | {scores['hit_at_k']:.4f} | {scores['recall_at_k']:.4f} | {scores['mrr_at_k']:.4f} |")
        lines += ["", "每题等权求平均；完整问题、标准 ID、检索排名、相似度和单题指标见同名 JSON 文件。", ""]
    return "\n".join(lines)


def run_evaluation(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    *,
    db_path: str | Path | None = None,
    collection_name: str = DEFAULT_COLLECTION,
    max_queries: int = 10,
    k: int = 5,
    batch_size: int = 1000,
    fetch_k: int | None = None,
    output: str | Path | None = None,
) -> dict[str, Any]:
    """筛选完整覆盖的问题，逐题评分并等权平均；失败不生成成功报告。

    max_queries 限制筛选之后的评估题数，按正相关 qid 首次出现的顺序选取。
    没有可评问题时仍输出报告，均值为 None，不调用模型。不会修改数据库。
    fetch_k 是片段检索预算，先按 source 首次出现去重再取前 k 篇文档。
    新集合默认 max(k, 50)，旧版单向量集合默认 k；上限均为 100。
    """
    for name, value in (("max_queries", max_queries), ("batch_size", batch_size)):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} 必须是正整数")
    if type(k) is not int or not 1 <= k <= 100:
        raise ValueError("k 必须是 1 到 100 的整数")
    if fetch_k is not None and (type(fetch_k) is not int or not k <= fetch_k <= 100):
        raise ValueError("fetch_k 必须是大于等于 k 且不超过 100 的整数")
    if not isinstance(collection_name, str) or not collection_name.strip():
        raise ValueError("collection_name 不能为空")
    created_at = datetime.now(timezone.utc)
    json_path = Path(output).expanduser().resolve() if output is not None else DEFAULT_RESULTS_DIR / f"report-{created_at:%Y%m%dT%H%M%S%fZ}.json"
    if json_path.suffix != ".json":
        raise ValueError("output 必须使用 .json 扩展名，同时生成同名 .md 报告")
    md_path = json_path.with_suffix(".md")
    if json_path.exists() or md_path.exists():
        raise FileExistsError("报告文件已存在，请选择新的 --output 路径，不会覆盖")

    dataset = T2Retrieval(data_dir)
    storage = Path(db_path).expanduser().resolve() if db_path is not None else dataset.data_dir / "storage"
    candidate_ids, metadata = _candidates(storage, collection_name, dataset)
    if fetch_k is None:
        fetch_k = max(k, 50) if metadata.get("indexing") == INDEXING else k
    # 扫描完整 qrels，不能先截断，否则会丢失非连续出现的正相关标注。
    grouped: dict[str, list[Judgment]] = {}
    for judgment in dataset.iter_qrels(batch_size):
        if judgment.score > 0:
            grouped.setdefault(judgment.query_id, []).append(judgment)
    eligible_ids = [
        query_id for query_id, judgments in grouped.items()
        if all(item.document_id in candidate_ids for item in judgments)
    ]
    selected_ids = eligible_ids[:max_queries]
    required_ids = set(selected_ids)
    queries = {}
    if required_ids:
        for query in dataset.iter_queries(batch_size):
            if query.id in required_ids:
                if query.id in queries:
                    raise ValueError(f"queries 存在重复 ID：{query.id}")
                queries[query.id] = query
        if required_ids - queries.keys():
            raise ValueError(f"queries 缺少所选问题：{sorted(required_ids - queries.keys())[0]}")

    print(f"候选资料 {len(candidate_ids)} 条；完整覆盖的问题 {len(eligible_ids)} 道；本次评估 {len(selected_ids)} 道", flush=True)
    kb = KnowledgeBase(storage, collection_name)
    results = []
    for index, query_id in enumerate(selected_ids, start=1):
        example = RetrievalExample(query=queries[query_id], documents=[], judgments=grouped[query_id])
        try:
            hits = kb.search(example.query.text, limit=fetch_k)
        except Exception as exc:
            raise RuntimeError(f"问题 ID={query_id} 检索失败，未生成完成报告") from exc
        if any(hit["source"] not in candidate_ids for hit in hits):
            raise ValueError("检索结果包含候选库以外的 source，请确认构建后没有修改集合")
        documents = []
        seen: set[str] = set()
        for chunk_rank, hit in enumerate(hits, start=1):
            if hit["source"] in seen:
                continue
            seen.add(hit["source"])
            documents.append({
                "rank": len(documents) + 1, "document_id": hit["source"],
                "score": hit["score"], "first_chunk_rank": chunk_rank,
            })
            if len(documents) == k:
                break
        retrieved_ids = [item["document_id"] for item in documents]
        results.append({
            "query_id": query_id,
            "query": example.query.text,
            "expected_document_ids": list(dict.fromkeys(item.document_id for item in example.judgments)),
            "retrieved_document_ids": retrieved_ids,
            "retrieved": documents,
            "retrieved_chunks": [
                {"rank": rank, "chunk_id": hit.get("id"), "document_id": hit["source"], "score": hit["score"]}
                for rank, hit in enumerate(hits, start=1)
            ],
            "fewer_than_k_documents": len(documents) < k,
            "metrics": score_query(example, retrieved_ids, k=k),
        })
        print(f"已评估 {index}/{len(selected_ids)} 道问题", flush=True)
    summary = {key: mean(item["metrics"][key] for item in results) if results else None for key in METRICS}
    report = {
        "created_at": created_at.isoformat(),
        "status": "completed" if results else "no_eligible_queries",
        "config": {
            "data_dir": str(dataset.data_dir), "db_path": str(storage), "collection": collection_name,
            "embedding_model": ollama.MODEL, "k": k, "fetch_k": fetch_k, "max_queries": max_queries,
            "ranking_policy": "bounded_chunk_search;first_source_occurrence;document_top_k",
            "batch_size": batch_size, "candidate_documents": len(candidate_ids),
            "candidate_chunks": metadata.get("chunk_count", metadata["document_count"]),
            "corpus_documents": dataset.counts["corpus"], "collection_metadata": metadata,
            "queries_sha256": _sha256(dataset.queries_path), "qrels_sha256": _sha256(dataset.qrels_path),
            "selection_policy": "all_positive_documents_in_candidates;first_seen_positive_qid_order",
            "scope": "local_retrieval_evaluation_not_official_benchmark",
        },
        "selection": {
            "positive_queries": len(grouped), "eligible_queries": len(eligible_ids),
            "excluded_incomplete_coverage": len(grouped) - len(eligible_ids),
            "excluded_by_limit": len(eligible_ids) - len(selected_ids), "evaluated_queries": len(results),
        },
        "summary": summary,
        "results": results,
    }
    json_text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    md_text = _markdown(report)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("x", encoding="utf-8") as stream:
        stream.write(json_text)
    with md_path.open("x", encoding="utf-8") as stream:
        stream.write(md_text)
    print(f"JSON 明细：{json_path}\nMarkdown 报告：{md_path}", flush=True)
    if results:
        print("平均指标：" + json.dumps(summary, ensure_ascii=False), flush=True)
    else:
        print("没有可评问题，未调用模型；请扩大候选库或重新准备候选资料。", flush=True)
    return report


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="T2Retrieval 批量检索评分，输出 JSON 和 Markdown 报告")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="原始 Parquet 目录")
    parser.add_argument("--db-path", type=Path, help="默认使用 data-dir/storage")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="已完成构建的评估集合")
    parser.add_argument("--max-queries", type=int, default=10, help="筛选后最多评估多少道题，默认 10")
    parser.add_argument("--k", type=int, default=5, help="Top-K，范围 1 到 100，默认 5")
    parser.add_argument("--batch-size", type=int, default=1000, help="Parquet 每批读取条数，不限制总题数")
    parser.add_argument("--fetch-k", type=int, help="片段检索上限，需 >= k 且 <= 100；切分集合默认 max(k, 50)")
    parser.add_argument("--output", type=Path, help="JSON 路径，同时生成同名 .md，默认 evals/results/ 下按时间命名")
    args = parser.parse_args()
    run_evaluation(
        args.data_dir, db_path=args.db_path, collection_name=args.collection,
        max_queries=args.max_queries, k=args.k, batch_size=args.batch_size, fetch_k=args.fetch_k, output=args.output,
    )


if __name__ == "__main__":
    main()
