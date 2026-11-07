# 检索评估

提供数据读取、corpus 直接入库、批量检索评分，以及 JSON 明细和 Markdown 报告。自动测试使用 mock 向量和临时 Qdrant；真实检索成绩以本地运行生成的报告为准。

## 目录

```text
evals/
├── data/                  # 原始 Parquet 不提交；storage/ 数据库快照随仓库保留
├── datasets/
│   ├── __init__.py        # 数据读取入口
│   └── t2retrieval.py      # 分批读取、规范化 ID、关联标注
├── tests/                 # 数据处理、入库与评分逻辑的离线测试
├── build_index.py         # 调用 src 的 Parquet 切分，再分批向量化入库
├── metrics.py             # 单题文档级指标
├── preview.py             # 数据预览命令
├── run.py                 # 批量检索、单题评分、平均指标和报告
├── results/               # 保留真实运行的 JSON/Markdown 报告，用于展示
└── README.md
```

评估数据库默认放在 `evals/data/storage/`，报告放在 `evals/results/`，两者均纳入版本管理，作为演示快照保留。原始 `evals/data/*.parquet` 下载文件仍被忽略，避免提交全量数据。日常知识库与评估库相互独立。

现有真实运行结果见[报告索引](results/README.md)，对应的完整切分集合为 `kb_eval_1`（1000 篇资料、1528 个片段）；203 道完整覆盖的问题参与评分。数据库同时保留历史集合，详见[快照说明](data/storage/README.md)。

## 准备数据

从以下两个数据集的 Files/data 页面下载文件，保留原文件名并放入 `evals/data/`：

- [C-MTEB/T2Retrieval](https://huggingface.co/datasets/C-MTEB/T2Retrieval)：`corpus-*.parquet`、`queries-*.parquet`。
- [C-MTEB/T2Retrieval-qrels](https://huggingface.co/datasets/C-MTEB/T2Retrieval-qrels)：`dev-*.parquet`。

当前只支持每种一个文件，不支持多分片或同时保留多份下载副本。

## 运行预览

在项目根目录执行：

```bash
uv run --group eval python -m evals.preview

# 可选：指定其他目录和每批读取条数
uv run --group eval python -m evals.preview --data-dir /path/to/data --batch-size 500
```

`pyarrow` 放在可选的 `eval` 依赖组中，不增加 MCP 运行时依赖。预览只读取文件，不要求启动 Ollama，不修改原始数据和日常知识库。

输出包括资料、问题及标注的条数，以及第一道有正相关标注的问题、它的全部相关资料和对应标注。

## Python 入口

```python
from evals.datasets import T2Retrieval

dataset = T2Retrieval("evals/data")
print(dataset.counts)

for record in dataset.iter_corpus(batch_size=1000):
    print(record.id, record.text)
    break

# 返回迭代器；每次产出一道问题，带上其全部正相关资料和标注。
for example in dataset.iter_examples(limit=10):
    print(example.query)
    print(example.documents)
    print(example.judgments)

# 也可以只取第一道完整样本。
example = dataset.first_example()
```

- `TextRecord`：`id`、`text`，用于资料和问题。
- `Judgment`：`query_id`、`document_id`、`score`。保留全部分值；正分值作为相关资料。
- `RetrievalExample`：`query: TextRecord`、`documents: list[TextRecord]`、`judgments: list[Judgment]`。一道题只产出一个样本，资料按 ID 去重，全部正相关标注及原始分值保留。

整数 ID 统一转换为字符串；正文不清洗、不切分、不去重，以免意外改变数据集含义。原始正文可能包含 HTML 标签。

## 一键运行

Ollama 启动且模型可用后，在项目根目录执行：

```bash
./scripts/eval.sh --max-documents 100 --max-queries 10 --chunk-size 1024 --k 5 --fetch-k 50
```

脚本先运行 `build_index`，成功后再运行 `run`；默认生成新的集合名和按时间命名的 JSON/Markdown 报告。`--chunk-size` 是字符数，`--max-documents` 是原始资料数，`--fetch-k` 是检索片段预算，`--k` 是去重后的文档排名截断。每次会构建新集合，不自动复用或覆盖旧集合。

可选参数：

```bash
./scripts/eval.sh --collection my_new_experiment --max-documents 100 --max-queries 10 --output evals/results/my_new_experiment.json
./scripts/eval.sh --help
```

还支持 `--data-dir`、`--db-path` 和 `--batch-size`，带空格的路径请加引号。指定的集合名不能已经存在，指定的 JSON 或同名 Markdown 也不能已经存在。若只查询已保存的集合，不要运行一键脚本，直接使用下面的 `evals.run` 命令，并指定 `--collection kb_eval_1`。

## 构建评估向量库

Parquet 读取和长文切分放在 `src/rag_mcp/chunk/parquet.py`，评估仅调用其 `iter_parquet_chunks()`，再复用 `Embeder` 和 `VectorDatabase`。正文采用与 TXT 相同的递归切分和定位逻辑，不转 TXT、不经过按文件内容去重的 `Fliter`。

```text
corpus.id + corpus.text → 一篇资料的多个 Chunk → Embeder → 独立 Qdrant collection
```

先启动 Ollama 并确保已有 `qwen3-embedding:0.6b`。下面的命令会真实请求模型，并写入数据库；不会自动运行。

```bash
# 先用 corpus 前 100 条验证流程，使用单独的联调集合。
uv run --group eval python -m evals.build_index --max-documents 100 --chunk-size 1024 --collection t2retrieval_chunked_smoke

# 全量入库：会对全部 corpus 逐条请求模型，耗时取决于本机性能。
uv run --group eval python -m evals.build_index

# 可选：数据目录、数据库目录、集合名与批大小。
uv run --group eval python -m evals.build_index --data-dir /path/to/data --db-path /path/to/data/storage --collection t2retrieval_experiment --batch-size 16
```

默认集合是 `t2retrieval_qwen3_baseline`，数据库目录是所选 `data-dir` 下的 `storage/`。每条 corpus 先按 TXT 规则切分，默认每片最多 1024 个字符（`--chunk-size`），不是 token 数。一篇资料的多个片段各有向量，`source` 都保存原始资料 ID，`heading_path=[]`，行号和字符偏移对应该片段在原始正文中的真实位置。正文不清洗、不开标题前缀、不静默截断。模型仍超限时直接报错，异常包含原始资料 ID、片段字符范围和 Ollama 错误正文。

不同 ID 即使正文完全相同也都会入库；相同 ID 重复出现则报错，避免评分时来源歧义。构造数据读取器仍要求三种 Parquet 均存在，但只有 corpus 正文用于向量化，问题和标注不入库。

`--batch-size` 控制 Parquet 行读取批次，以及每批缓存和写入的片段数量，不表示模型并发或 HTTP 批量请求；当前 `Embeder` 仍逐片请求 Ollama。读取器只缓存一批记录、一篇资料的片段和已见 ID 集合；入库不缓存全部正文或向量。

`--max-documents` 只取 corpus 前 N 条，**不是抽取 N 道问题**，也不保证包含所选问题的全部相关资料。它仅用于流程联调；这种前缀候选库不能用于宣称完整 T2Retrieval 基准成绩。

### 完整性与重复运行

- 同名集合已存在时直接报错，不追加、不覆盖、不清空；重试请选择新集合名。
- 所有批次写完后，关闭并重新打开数据库，核对实际记录数，成功才设置集合 metadata 的 `build_complete=True`。
- 新集合 metadata 的 `indexing=chunked_documents_v1`，分别记录 `document_count`、`chunk_count`、`chunk_size`、字符单位、切分规则、模型和完整 corpus 文件的 SHA-256。不能将新片段追加到旧的单向量集合。
- 中断或异常可能留下部分集合，未完成的集合不可用于正式评估；不会自动续传、重试或删除。调整上下文等参数后重跑仍需使用新集合名。后续评估入口应要求 `build_complete is True`，目前通用 `KnowledgeBase.search()` 不会检查这个评估专用标记。
- 本地 Qdrant 同一目录不能被多个进程同时打开，构建时不要同时运行针对同目录的查询。
- 空 corpus 返回 0，不创建新的数据库或集合。

Python 入口返回实际写入的片段数（可能大于原始资料数）：

```python
from evals.build_index import build_index

count = build_index("evals/data", collection_name="t2retrieval_smoke_python", max_documents=100)
```

构建成功后，`KnowledgeBase(db_path="evals/data/storage", collection_name="t2retrieval_qwen3_baseline")` 可读取该集合。评分时取搜索结果的 `source`，不要使用 Point UUID 的 `id`，也不要用标准资料 ID 过滤查询。

## 批量检索与结果报告

对已经完成构建的集合运行（集合名改为你实际使用的名称）：

```bash
uv run --group eval python -m evals.run --collection t2retrieval_chunked_smoke --max-queries 10 --k 5 --fetch-k 50 --output evals/results/smoke.json
```

生成 `smoke.json`（单题明细、标准 ID、原始片段排名、去重后的文档排名、相似度、单题和平均指标、参数及文件指纹）和 `smoke.md`（可阅读的汇总报告）。不指定 `--output` 时在 `evals/results/` 按时间命名；已有同名 JSON 或 Markdown 时拒绝覆盖。

参数还包括 `--data-dir`、`--db-path` 和 `--batch-size`；数据库默认位于所选数据目录下的 `storage/`。`--k` 支持 1 到 100，默认 5。`--max-queries` 默认 10，限制**筛选之后**实际评估的问题数；想评估更多问题时显式提高此值。

入口检查集合完成标记、模型、corpus SHA-256、原始文档数和片段数，再读取全部正相关标注。新集合允许多个片段共用 `source`，同时兼容旧版 `one_record_one_vector` 集合。仅选择全部正相关资料均已入库的问题，按 qid 首次出现在正相关标注中的顺序评估；搜索不使用答案 ID 过滤。

`--fetch-k` 控制检索多少个片段，范围为 K 到 100；新集合默认 `max(K, 50)`，旧版默认 K。按原始片段排名中每个 `source` 首次出现的位置得到文档排名，再取前 K 篇评分。预算内不足 K 篇不同文档时不补齐，JSON 的 `fewer_than_k_documents` 会标出；这不是无限量检索后得到的全库文档 Top-K。报告保留原始 `retrieved_chunks` 和去重后的 `retrieved`。逐题复用 `score_query()`，各项指标按问题等权平均，不平均相似度。

没有满足条件的问题时，不调用模型，仍生成说明报告，指标为 `null` 而非 0；请扩大候选库或重新准备相关资料和干扰资料。单题搜索异常时保留问题 ID 和原始异常，不将失败题当成零分或生成完成报告。执行期间不要在其他进程修改同一数据库。

缩小候选库及按标注筛选问题会改变评估难度，报告不能当作完整 T2Retrieval 官方基准成绩。运行需要 Ollama，仅生成查询向量，不重新生成资料向量或写入候选资料。

## 单题评分

```python
from evals.metrics import score_query

example = dataset.first_example()
# 仅演示评分：这里人为构造排名，不是实际模型输出。
retrieved_ids = ["unrelated-demo", example.documents[0].id]
print(score_query(example, retrieved_ids, k=5))
```

输入应是按检索排名排列的原始文档 ID，不能直接传 Qdrant 片段 UUID。函数先按首次出现顺序去重，再取前 K 篇文档；重复片段不会占用多个文档名次。

- `hit_at_k`：前 K 篇是否至少命中一篇标准相关资料，取 0 或 1。
- `recall_at_k`：命中的不同相关资料数 / 全部不同的正相关资料数。
- `mrr_at_k`：首篇相关资料排名的倒数，未命中为 0。单题实际是倒数排名，跨题取平均后才是 MRR@K。

评分依据是该题的全部 `score > 0` 标注，不依赖 `documents` 列表长度，重复标注不增加分母。正相关分值不作权重；未标注为正相关的文档按未命中处理，这不等于证明它在语义上不相关。

不足 K 篇时按实际结果评分，空结果返回全零。没有正相关标注的问题会报错，调用方需要明确决定如何处理，不能悄悄当作零分或满分。非法 K、文档 ID、非有限标注分值和混入其他问题的标注也会报错。

返回字典的键为 `hit_at_k`、`recall_at_k`、`mrr_at_k`；调用方应在报告中同时记录 K。函数不修改传入的数据，也不计算跨题汇总。

## 校验范围

构造读取器时检查文件是否唯一、必需列是否存在。若 corpus 和 queries 大小相同，再计算内容指纹以排除重复下载。读取记录时检查 ID、正文和标注分值。

`iter_examples()` 按 qid 汇总 `score > 0` 的标注，然后按 ID 关联问题和资料，逐个 `yield RetrievalExample`。问题顺序为 qid 首次出现在正相关标注中的顺序；资料顺序为该题标注中的首次出现顺序，重复文档 ID 只保留一份正文，但不会丢弃原始正相关标注。

`limit` 限制问题数，不是资料数或标注数。即使某道题的标注分散在 dev 文件的不同位置，也会全部收集；没有正相关标注时迭代器为空。`first_example()` 复用 `iter_examples(limit=1)`，返回第一道题的全部相关资料；没有样本时报告错误。

每个文件最多扫描一遍，不会为每道题重复扫描 corpus。首次消费迭代器时会先建立所选问题及相关资料的内存索引，再逐个返回样本；**返回迭代器不等于全流程常量内存**。全量关联仍可能占用较多内存，建议先使用 `limit=10` 等小规模预览。

所选问题的正相关标注引用缺失，或者所选问题/资料存在重复 ID 时，会报告错误；未选中问题的引用和非正相关标注的引用不在本次关联校验范围内。资料全文不清洗，关联检查也不保证标注本身语义正确。

## 测试

```bash
uv run --group eval python -m unittest discover -s evals/tests -v
```

使用临时生成的小型 Parquet、mock embedding 和临时本地 Qdrant，不需要大数据文件和模型服务。覆盖通用 Parquet 可配置列、可选依赖按需加载、长文切分与精确偏移、原始 ID/正文保留、相同正文不同 ID、独立集合、重复构建拒绝、分批入库、失败标记、文档/片段计数、文档级去重和检索预算。原有业务测试仍使用 `python -m unittest discover -s tests`。

后续评估流程与注意事项见[评估说明](../docs/evaluation.md)。
