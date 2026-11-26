"""片段级 BM25：中文分词、倒排统计及确定性相关度排序，不请求模型。"""

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from heapq import nsmallest
from typing import TypedDict

import jieba


@dataclass(frozen=True)
class SearchChunk:
    """参与检索的片段；id 为稳定片段 ID，source 为评分使用的原始资料 ID。"""

    id: str
    source: str
    text: str


class SearchHit(TypedDict):
    """片段检索结果；score 仅用于 BM25 内部排序，不是概率或向量相似度。"""

    id: str
    source: str
    score: float


class BM25Index:
    """在内存中构建片段倒排索引；分词仅使用 jieba 自带词典，不学习测试问题。

    k1 默认 1.2，必须为有限正数，控制词频饱和；b 默认 0.75，范围 [0, 1]，
    控制片段词数相对平均词数的长度归一化。参数在索引构建时固定。
    IDF 使用 log(1 + (N - df + 0.5) / (df + 0.5))，始终为正。
    所有片段（含无有效词片段）计入 N 和平均长度，整个索引常驻内存。
    """

    @staticmethod
    def validate_parameters(k1: float, b: float) -> None:
        """在读取候选库之前校验词频和长度参数；无效值抛出 ValueError。"""
        for name, value in (("k1", k1), ("b", b)):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{name} 必须是有限数值")
        if k1 <= 0 or not 0 <= b <= 1:
            raise ValueError("k1 必须大于 0，b 必须在 0 到 1 之间")

    def __init__(self, chunks: Iterable[SearchChunk], *, k1: float = 1.2, b: float = 0.75) -> None:
        self.validate_parameters(k1, b)
        self.k1 = k1
        self.b = b
        self.chunks = sorted(chunks, key=lambda chunk: chunk.id)
        if not self.chunks:
            raise ValueError("BM25 候选片段不能为空")
        if len({chunk.id for chunk in self.chunks}) != len(self.chunks):
            raise ValueError("候选片段存在重复 ID")
        self._tokenizer = jieba.Tokenizer()
        self._postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self._lengths: list[int] = []
        for index, chunk in enumerate(self.chunks):
            if any(not isinstance(value, str) or not value.strip() for value in (chunk.id, chunk.source, chunk.text)):
                raise ValueError("片段 id、source 和 text 必须为非空字符串")
            tokens = self.tokenize(chunk.text)
            self._lengths.append(len(tokens))
            for token, frequency in Counter(tokens).items():
                self._postings[token].append((index, frequency))
        self.average_length = sum(self._lengths) / len(self.chunks)
        self._idf = {
            token: math.log1p((len(self.chunks) - len(postings) + 0.5) / (len(postings) + 0.5))
            for token, postings in self._postings.items()
        }

    def tokenize(self, text: str) -> list[str]:
        """正文和查询统一小写、jieba 精确分词且关闭 HMM；去除纯空白和纯符号。

        不删除停用词，不加载自定义词典；中文字符和包含字母/数字的词保留。
        不改写原文，只对用于统计的词项执行上述规范化。
        """
        return [
            token for token in self._tokenizer.cut(text.lower(), HMM=False)
            if any(character.isalnum() for character in token)
        ]

    def search(self, query: str, *, limit: int = 50) -> list[SearchHit]:
        """返回最多 limit 个片段的 id、source 和 score，不按标准答案过滤。

        limit 是正整数片段预算。重复查询词只计一次；空查询、无有效词或
        全部词均未出现时返回空列表，不用零分资料补齐。仅返回正分结果，
        按分数降序、片段 ID 字符串升序打破平分，保证重复运行结果稳定。
        """
        if not isinstance(query, str):
            raise ValueError("query 必须是字符串")
        if type(limit) is not int or limit <= 0:
            raise ValueError("limit 必须是正整数")
        scores: dict[int, float] = defaultdict(float)
        for token in dict.fromkeys(self.tokenize(query)):
            for index, frequency in self._postings.get(token, []):
                normalization = 1 - self.b + self.b * self._lengths[index] / self.average_length
                scores[index] += self._idf[token] * frequency * (self.k1 + 1) / (frequency + self.k1 * normalization)
        ranked = nsmallest(limit, scores, key=lambda index: (-scores[index], self.chunks[index].id))
        return [
            {"id": self.chunks[index].id, "source": self.chunks[index].source, "score": scores[index]}
            for index in ranked
        ]
