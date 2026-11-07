"""将单个或多个 Chunk 转换为带元数据的向量结果。"""

from dataclasses import asdict
from typing import overload

from ..chunk.schema import Chunk
from .ollama import embed_text
from .schema import Embed, EmbedMetadata


class Embeder:
    """使用 Ollama 向量化片段；保留原文和来源，不修改输入。"""

    @overload
    def embed(self, chunks: Chunk) -> Embed: ...

    @overload
    def embed(self, chunks: list[Chunk]) -> list[Embed]: ...

    def embed(self, chunks: Chunk | list[Chunk]) -> Embed | list[Embed]:
        """单个 Chunk 返回 Embed，列表返回按输入顺序排列的 list[Embed]。

        空列表返回 []，不请求模型。列表会先整体校验，再逐个请求向量；
        类型、空白正文及模型错误直接抛出。标题路径用于向量化上下文，
        metadata.text 始终保存原始正文。
        """
        if isinstance(chunks, Chunk):
            items = [chunks]
        elif isinstance(chunks, list):
            items = chunks
        else:
            raise TypeError("chunks 必须是 Chunk 或 list[Chunk]")

        for chunk in items:
            if not isinstance(chunk, Chunk):
                raise TypeError("chunks 中的元素必须是 Chunk")
            if not isinstance(chunk.text, str):
                raise TypeError("chunk.text 必须是字符串")
            if not chunk.text.strip():
                raise ValueError("chunk.text 不能为空或只有空白")

        results = [self._embed_chunk(chunk) for chunk in items]
        return results[0] if isinstance(chunks, Chunk) else results

    def _embed_chunk(self, chunk: Chunk) -> Embed:
        heading = " > ".join(chunk.metadata.heading_path)
        text = f"{heading}\n\n{chunk.text}" if heading else chunk.text
        return Embed(
            vector=embed_text(text=text),
            metadata=EmbedMetadata(**asdict(chunk.metadata), text=chunk.text),
        )
