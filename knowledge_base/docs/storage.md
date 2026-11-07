# 向量存储

[返回项目首页](../README.md) · [架构总览](architecture.md)

`vector_databbase/` 提供 Qdrant 本地持久化封装，公开 `VectorDatabase`。初始化传入数据库目录，`self.client` 是底层 `QdrantClient`，不需要单独启动 Qdrant 服务。

```python
from rag_mcp.embed import Embed, EmbedMetadata
from rag_mcp.vector_databbase import VectorDatabase

embeds = [
    Embed(
        vector=[1.0, 0.0, 0.0],  # 示例向量；实际使用 Embeder 的输出
        metadata=EmbedMetadata(
            source="/knowledge-base/guide.md",
            heading_path=["指南", "安装"],
            start_line=2,
            end_line=3,
            start_index=11,
            end_index=15,
            text="正文。\n",
        ),
    ),
]

with VectorDatabase(db_path="./.qdrant") as db:
    # 创建新集合时执行一次；已有集合可直接 upsert。
    db.create_collection(collection_name="knowledge", vector_size=len(embeds[0].vector))
    point_ids = db.upsert(collection_name="knowledge", embeds=embeds)
```

- `create_collection(collection_name, vector_size, embedding_model=...)` 创建空集合，使用 `Cosine` 余弦相似度，返回底层客户端的布尔结果。可选的模型标识保存在集合元数据中，构建和语义搜索会检查是否匹配；同名集合已存在时抛出异常，不清空或覆盖原集合。
- `upsert(collection_name, embeds)` 接收 `list[Embed]`，将 `vector` 保存为 Point 的向量、`asdict(metadata)` 保存为 payload，等待写入完成后按输入顺序返回 Point UUID 列表。可选的 `processing_keys` 参数接收 `source -> 文件处理标识`，同时保存 `processing_key`、`ingestion_id`、文件内 `chunk_index` 和 `chunk_count`；此时必须一次传入每个文件的全部片段。省略时保持原有元数据结构。`upsert(..., [])` 返回 `[]`，不访问数据库；输入类型和数据库错误直接抛出。
- Qdrant 按 Point ID 判断新增或覆盖，不按正文自动去重。本封装每次生成新 UUID，因此直接重复调用 `upsert` 仍会新增记录。[构建流程中的 `Fliter`](ingestion.md) 在切分、向量化和写入之前执行文件去重。
- 数据保存在 `db_path`，关闭后重新打开仍可读取。支持 `with VectorDatabase(db_path) as db`：正常结束或抛出异常都会自动调用 `close()` 释放文件锁，块内异常继续向上传递。也可手动调用 `close()`；同一路径不要同时打开多个本地客户端。

MCP 的检索和读取也使用这个持久化数据库，不再使用每次查询时重新生成向量的内存知识库。

## 随仓库保存的评估数据库

`evals/data/storage/` 保留 Qdrant 本地数据库原文件，便于展示和检查；它不是 Qdrant 服务端的快照导出格式。`kb_eval_1` 是当前报告对应的完整集合，包含 1000 篇原始资料、1528 个片段，片段按原始资料 ID 共享 `source`。文档数与片段数分别保存在集合 metadata 中，只有 `build_complete is True` 才能用于评估。

该目录还原样保留一个旧版完整集合和两个未完成集合，详见[快照清单](../evals/data/storage/README.md)。不删除历史集合，也不将未完成集合算作有效结果。

报告和数据库纳入 Git 是为了展示；数据库是可变二进制文件，后续运行会产生变更并增加仓库历史体积。需要试用时建议复制到一个新的临时目录，通过 `--db-path` 指定副本，避免修改保存的基线。使用 `uv.lock` 固定的客户端版本，不要让多个进程同时访问同一目录。
