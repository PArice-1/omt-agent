# 构建与去重

[返回项目首页](../README.md) · [架构总览](architecture.md)

## 构建并验证知识库

`build_kb` 接收 `list[str | Path]`，目录和具体文件可以混合传入：

```python
from pathlib import Path
from rag_mcp.build_kb import build_kb

written = build_kb(
    ["./knowledge-base", Path("./other-docs"), "./notes/selected.md"],
    db_path="./.qdrant",
    collection_name="knowledge",
    chunk_size=2048,
)
print(f"本次新增 {written} 个片段")
```

- 目录递归扫描 MD/TXT，显式传入的不支持类型会报错。
- 重复路径、重叠目录和符号链接别名会合并；最终文件按绝对路径排序。
- 排除 `db_path` 内的文件，所有输入统一写入同一个存储目录和集合。
- `db_path` 默认是当前工作目录下的 `./knowledge-base/storage`，不会随输入目录改变；集合默认 `knowledge`。
- 返回本次新增片段数，不返回内存向量。空列表、空目录、无正文或全部重复时返回 `0`，不调用模型。
- 任意输入路径无效时，在向量化和写入前报错，不悄悄忽略；`paths` 必须是列表，单个路径需写成 `[path]`。

CLI 与 Python 入口使用同一实现：

```bash
uv run rag-build-kb ./knowledge-base ./other-docs ./notes/selected.md \
  --db-path ./.qdrant --collection knowledge --chunk-size 2048
# 等价模块入口：
uv run python -m rag_mcp.build_kb ./knowledge-base ./other-docs --db-path ./.qdrant
```

构建依次执行 `Fliter → Chunker → Embeder → VectorDatabase`。向量维度取自实际模型输出；写入后关闭并重新打开数据库，校验新增记录数，并核对本次首条片段正文。不会打印资料正文。

重复文件在切分前过滤，但仍需读取字节计算哈希。修改文件或切分配置后追加新版本，不自动删除旧记录；更换 embedding 模型必须使用新集合，不能将不同模型混入已记录模型的集合，即使维度相同也不允许。历史集合没有模型元数据时，无法自动验证模型，需自行保证兼容或重建到新集合。

离线联调测试使用真实切分和临时 Qdrant 数据库，mock Ollama 请求，并在关键场景监测 `Chunker` 调用，覆盖多目录与具体文件混合输入、重叠路径、排除存储目录、重复构建不切分、改名、文件修改、配置变更、模型隔离、旧记录重建、模型失败及部分写入后重试：

```bash
uv run python -m unittest discover -s tests -p test_build_kb.py -v
```

## 过滤规则与持久化去重

```text
src/rag_mcp/fliter/
├── __init__.py  # 公开 Fliter、FileSelection、ProcessingProfile 和过滤函数
├── schema.py    # 文件选择结果和处理配置
├── fliter.py    # 注册规则、按顺序执行、分页读取 Qdrant 完整性元数据
└── duplicate.py # 文件处理标识计算和重复文件过滤
```

`Fliter(db, collection_name).filter(files)` 接收文件路径序列，返回 `FileSelection(files, processing_keys)`：`files` 是待切分的绝对路径列表，`processing_keys` 是绝对路径到处理标识的映射。不传数据库时只在当前批次去重；相同文件按输入顺序保留第一份，副本路径不会另外存为来源。

下面展示手动串联流程，假设 `db` 是已打开的 `VectorDatabase`、`files` 是已发现的文件路径序列，目标集合已创建；完整构建通常直接调用前面的 `build_kb()`。

```python
from rag_mcp.chunk import Chunker
from rag_mcp.embed import Embeder, ollama
from rag_mcp.fliter import Fliter, ProcessingProfile

chunker = Chunker(chunk_size=2048)
profile = ProcessingProfile(chunk_size=chunker.chunk_size, embedding_model=ollama.MODEL)
selection = Fliter(db, "knowledge", profile=profile).filter(files)
chunks = chunker.chunk(selection.files)
embeds = Embeder().embed(chunks)
db.upsert("knowledge", embeds, processing_keys=selection.processing_keys)
```

处理标识采用 `sha256:file-v1:` 前缀，基于**原始文件字节的 SHA-256、解析器类型（MD/TXT）、chunk_size、切分逻辑版本、embedding 模型及输入拼接逻辑版本**计算，不包含路径。文件改名、复制到其他路径后仍能识别；相同字节的 MD 和 TXT 不会混为一份，扩展名大小写不影响判断。原始内容中任何字节变化都可能触发重新处理，不进行语义或切分后正文去重。不同文档共有的片段、文档内部重复段落均保留。

`ProcessingProfile` 必须与实际切分和向量化配置一致；`build_kb` 自动使用当前 `Chunker.chunk_size` 和 `ollama.MODEL`。修改切分规则或模型输入拼接逻辑时，需同步更新 `chunk_version` 或 `embedding_version`；同名模型的权重变更也需要人为更新版本标识。更换模型应使用新集合，不能仅因维度相同就混用向量；现有集合维度也不会自动迁移。

默认规则为 `remove_duplicates`；自定义规则的形式为 `(selection: FileSelection, stored_keys: set[str]) -> FileSelection`，通过 `Fliter(..., rules=[...])` 指定顺序，`rules=[]` 不执行过滤规则。规则应保持返回文件与处理标识映射一致，且不修改输入。

入库时处理标识与 `ingestion_id`、文件内片段编号和总数一起写入 Qdrant payload，无需额外数据库。过滤时每页读取 256 条当前集合的完整性元数据，不读取正文或向量；按来源、处理标识、写入批次和预期片段数分组，只认可具有全部唯一编号的完整文件。重复记录不会补足缺失编号，不同写入批次或来源的残片不会被拼成完整文档。模型调用失败不记录处理标识；部分写入允许重试，但不自动清理原有残留记录。集合删除后处理信息随记录删除，各集合互不影响。

旧版本的 `document_hashes` / `document_fingerprint` 已替换为 `processing_keys` / `processing_key`。只有切分结果的旧记录无法准确还原原始文件哈希，因此不会直接用来跳过文件：首次构建会重新处理并追加新记录，之后才可在切分前跳过。已有历史记录不会删除。

构建应串行执行，且源文件在过滤到入库期间必须保持不变；当前不提供文件内容快照，读取检查与写入也不构成跨进程事务。没有可入库正文的文件不写完成记录，下次仍会检查、切分。每次过滤仍需扫描当前集合的完整性元数据，后续数据量增大时可再添加独立索引。

```bash
uv run python -m unittest discover -s tests -p test_fliter.py -v
```

MCP 启动前自动构建的参数、日志与失败行为，见 [MCP 与检索](mcp.md)。
