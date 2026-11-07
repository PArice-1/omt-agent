# 片段向量化

[返回项目首页](../README.md) · [架构总览](architecture.md)

```python
from dataclasses import asdict

from rag_mcp.chunk import Chunker
from rag_mcp.embed import Embeder

chunks = Chunker().chunk(["./knowledge-base/guide.md", "./knowledge-base/notes.txt"])
embeder = Embeder()

results = embeder.embed(chunks)       # list[Chunk] -> list[Embed]
if chunks:
    result = embeder.embed(chunks[0]) # Chunk -> Embed
    print(result.vector)
    print(result.metadata.text)
    print(asdict(result))
```

单个 `Chunk` 返回一个 `Embed`；列表输入始终返回列表，包括只有一个片段的列表。`embed([])` 返回 `[]`，不请求模型。列表先校验输入类型和正文是否非空，再按顺序逐个请求模型；类型、空白正文和模型错误直接抛出。

向量结果顶层只有 `vector` 和 `metadata`。`EmbedMetadata` 继承 `ChunkMetadata` 的全部字段，并增加 `text`，例如：

```python
{
    "vector": [0.25, -0.5],
    "metadata": {
        "source": "/absolute/path/guide.md",
        "heading_path": ["指南", "安装"],
        "start_line": 2,
        "end_line": 3,
        "start_index": 11,
        "end_index": 15,
        "text": "正文。\n",
    },
}
```

`metadata.text` 保存未经拼接的原始正文，来源和定位字段与输入 chunk 一致。请求向量时，有标题的片段使用 `标题 > 子标题\n\n正文` 提供上下文，无标题片段直接使用正文。结果的标题路径列表独立于输入，修改结果不会改变原 chunk。

```text
src/rag_mcp/embed/
├── __init__.py # 公开 Embeder、Embed、EmbedMetadata
├── schema.py   # vector + metadata，原文 text 放入 metadata
├── embeder.py  # 单个/列表 Chunk 的向量化入口
└── ollama.py   # 字符串向量化请求与响应校验
```

Ollama 默认使用 `http://localhost:11434/api/embed` 和 `qwen3-embedding:0.6b`，配置位于 `embed/ollama.py`。请求显式指定 `options.num_ctx=8192`，并保留 `truncate=False`：上下文按 token 而非字符计算，超限直接报错，不自动截断。增大上下文会增加内存或显存开销；8192 不保证容纳所有 corpus 正文。

HTTP 请求失败时，在原 `HTTPError` 消息中补充最多 4096 字节的 Ollama 响应正文，便于区分输入超限、模型不存在等原因。保留原异常实例、状态码与类型，不额外打印日志；读取错误正文失败时仍抛出原 HTTP 异常。

字符串向量化统一使用 `rag_mcp.embed.ollama.embed_text(text)`，查询与 `Embeder` 共用同一份上下文和请求实现。旧的 `embeding.py` 兼容入口已删除。
