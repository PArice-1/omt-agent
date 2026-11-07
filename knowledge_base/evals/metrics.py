"""文档级检索指标：只比较标准标注和检索 ID，不调用模型或数据库。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .datasets import RetrievalExample


def score_query(
    example: RetrievalExample,
    retrieved_document_ids: list[str],
    k: int = 5,
) -> dict[str, float]:
    """计算一道题的 Hit@K、Recall@K 和倒数排名。

    输入必须是按检索排名排列的原始文档 ID，不是片段 UUID。
    先按首次出现顺序去重，再取前 k 篇文档；不足 k 篇不补齐。
    标准集合来自该题 score > 0 的全部标注，重复标注只算一篇资料，
    正分值只表示相关，不按分值加权；未标注为正相关的 ID 按未命中处理。

    返回 hit_at_k、recall_at_k、mrr_at_k。最后一项是单题的倒数排名，
    跨题取平均才是 MRR@K；k 需由调用方随报告一起记录。
    空检索结果返回全零；无正相关标注则报错，不擅自计零或跳过。
    """
    if type(k) is not int or k <= 0:
        raise ValueError("k 必须是正整数")
    if not isinstance(retrieved_document_ids, list):
        raise TypeError("retrieved_document_ids 必须是 list[str]")
    if any(not isinstance(item, str) or not item.strip() for item in retrieved_document_ids):
        raise ValueError("retrieved_document_ids 中的 ID 必须是非空字符串")

    expected_ids: set[str] = set()
    for judgment in example.judgments:
        if judgment.query_id != example.query.id:
            raise ValueError("标注的 query_id 与当前问题 ID 不一致")
        if not isinstance(judgment.document_id, str) or not judgment.document_id.strip():
            raise ValueError("标注的 document_id 必须是非空字符串")
        if type(judgment.score) not in (int, float) or not math.isfinite(judgment.score):
            raise ValueError("标注的 score 必须是有限数值")
        if judgment.score > 0:
            expected_ids.add(judgment.document_id)
    if not expected_ids:
        raise ValueError("当前问题没有正相关标注，无法计算 Recall@K")

    # dict 保留插入顺序：同一文档多次出现时，只保留第一次的排名。
    ranked_ids = list(dict.fromkeys(retrieved_document_ids))[:k]
    matched_ids = expected_ids.intersection(ranked_ids)
    first_rank = next(
        (rank for rank, document_id in enumerate(ranked_ids, start=1) if document_id in expected_ids),
        None,
    )

    return {
        "hit_at_k": float(bool(matched_ids)),
        "recall_at_k": len(matched_ids) / len(expected_ids),
        "mrr_at_k": 1.0 / first_rank if first_rank is not None else 0.0,
    }
