# 检索评估

本文中的模块级命令在仓库的 `knowledge_base/` 目录执行；根目录命令见 [开发说明](../development.md).

[返回项目首页](../../knowledge_base/README.md) · [架构总览](architecture.md) · [评估目录使用说明](../../knowledge_base/evals/README.md)

## 标准数据与关联规则

使用 T2Retrieval，不再使用手写笔记和教学题目：

| 文件 | 必需字段 | 作用 |
|---|---|---|
| `corpus-*.parquet` | `id`、`text` | 检索候选资料 |
| `queries-*.parquet` | `id`、`text` | 测试问题 |
| `dev-*.parquet` | `qid`、`pid`、`score` | 问题与相关资料的标准标注 |

```text
标注 qid → queries.id → 问题正文
标注 pid → corpus.id  → 相关资料正文
```

文件行顺序不能作为配对依据，所有对应关系都通过 ID 建立。标注分值不是检索器计算的相似度，也不是答案正确概率。

在项目根目录执行：

```bash
uv run --group eval python -m evals.preview
```

当前命令只检查文件、字段，以及第一道有正相关标注的问题与全部相关资料的对应关系，不调用 embedding，也不计算评估指标。`T2Retrieval.iter_examples()` 已支持按问题分组并迭代返回完整样本；可用 `limit` 限制关联的问题数量。完整用法、校验范围及测试命令见[评估目录说明](../../knowledge_base/evals/README.md)。

## 已提供：复用通用 Parquet 切分后入库

`evals/build_index.py` 调用 `src/rag_mcp/chunk/parquet.py` 的通用流式入口，将每篇正文按与 TXT 相同的规则切成多个 `Chunk`，再调用现有 `Embeder` 写入独立集合。默认每片最多 1024 个字符，不转 TXT，也不经过文件内容去重。

- 默认数据库：`evals/data/storage/`，默认集合：`t2retrieval_qwen3_baseline`。
- 一篇资料的多个片段共用原始 corpus ID 作为 `source`；相同正文的不同 ID 都保留，字符位置相对于各自原始正文。
- 只向量化 corpus，不把 queries 或 qrels 当作资料，不添加编造的标题。
- 按批写入，拒绝已有同名集合；写完后重开数据库核对记录数，标记 `build_complete=True`。
- 集合中分别记录模型、corpus SHA-256、文档数、片段数、片段大小和切分规则。失败可能留下未完成集合，不自动续传或删除。

可以先用 `--max-documents 100 --collection t2retrieval_smoke` 联调。这个选项只是 corpus 前缀截取，不保证任何问题的相关资料覆盖，因此不能作为完整基准的候选库。具体命令与失败处理见[评估目录说明](../../knowledge_base/evals/README.md#构建评估向量库)。

`evals.run` 对已完成集合执行查询，生成 JSON 和 Markdown 报告。也可用 `./scripts/eval.sh --chunk-size 1024 --max-documents 100 --max-queries 10 --k 5 --fetch-k 50` 一键完成新集合构建及评估；该脚本每次先入库，已有集合只查询时直接调用 `evals.run`。自动测试使用 mock 向量和临时 Qdrant，真实成绩以本地模型运行的报告为准。

## 已保存的展示结果

仓库保留[真实运行报告](../../knowledge_base/evals/results/README.md)和[本地数据库快照](../../knowledge_base/evals/data/storage/README.md)，原始 Parquet 需从上游另行下载。示例集合 `kb_eval_1` 包含 corpus 前 1000 篇资料，切分为 1528 个片段；203 道问题满足全部正相关资料在库的条件，K=5、片段检索预算为 50。

平均 Hit@5 为 0.990148、平均 Recall@5 为 0.837536、MRR@5 为 0.990148。其余 22609 道有正相关标注的问题因候选资料覆盖不全而排除，不能把该结果解释为完整数据集成绩。快照中的历史未完成集合保留用于说明构建失败状态，不用于评分。

## BM25 与已有向量结果对照

`evals.run_bm25` 直接复用 `evals.run` JSON 中已评问题的正文、全部正相关资料 ID，以及对应 Qdrant 集合的全部候选片段。不需要重新下载 Parquet，也不请求 Ollama；向量排名来自已有报告，不是本次重跑，因此不比较查询耗时。现有 `search_keyword` 是子串匹配，不是本入口使用的 BM25。

在 `knowledge_base/` 目录执行：

```bash
uv sync --frozen --group eval
uv run --frozen --no-sync --group eval python -m evals.run_bm25 \
  --baseline-report evals/results/report-20261107T082120064449Z.json \
  --db-path evals/data/storage \
  --output evals/results/my-bm25-comparison.json
```

生成指定 JSON 和同名 Markdown：

- Markdown 包含 BM25/向量的平均 Hit@K、Recall@K、MRR@K、差值以及逐题指标。
- JSON 保留完整问题、正相关 ID、BM25 原始片段排名及得分、去重后的文档排名、向量文档排名及重算指标、参数、基线文件 SHA-256 和本次候选片段正文指纹。
- 不指定 `--output` 时，在 `evals/results/` 下生成带 UTC 时间的 `bm25-*.json` 和 `.md`；任何同名报告存在都会拒绝覆盖。

### 对齐与隔离

K、fetch_k、候选片段和实际问题集合完全继承向量报告，不重新选择题目，不用正相关 ID 过滤搜索。先在 fetch_k 预算内检索片段，按 source 首次出现去重，再取前 K 篇；不足 K 篇不补齐。重复正相关 ID 只算一篇资料；不使用标注分值加权，与现有 `score_query()` 一致。基线无可评问题时输出 null 指标，不计零分。

数据库必须是静止快照，运行期间不得有其他进程写入。入口复制整个本地 Qdrant 目录到临时目录后才打开客户端，需要额外临时磁盘空间；不在原数据库获取锁或修改原集合。读取时验证构建完成标记、全部构建元数据、候选文档/片段计数、相关资料覆盖及基线返回片段的 ID/来源。片段正文、倒排表常驻内存，不是面向全量大库的服务实现。异常停止，不将失败问题计为零分。

### 算法和固定参数

`evals/bm25.py` 实现 BM25 的正 IDF 版本：

```text
score(q, d) = Σ IDF(t) × f(t,d) × (k1 + 1)
                       / [f(t,d) + k1 × (1 - b + b × |d| / avgdl)]
IDF(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
```

N、df 和长度均以**片段**为统计单位，长度是分词后的词数，不是字符数。正文与问题统一小写，使用 jieba 自带词典精确分词、关闭 HMM，过滤纯符号与空白；不删除停用词、不加载自定义词典。重复查询词只计一次，词典不从问题或标准答案中训练。

`--k1` 默认 1.2，必须为有限正数，控制词频饱和；`--b` 默认 0.75，范围 [0, 1]，控制长度归一化。参数在本次索引构建时固定，不自动搜索最优参数。只有正分匹配进入排名，无匹配返回空列表，不补零分资料；同分按片段 ID 字符串升序打破平分。BM25 分数不是概率，不能直接与向量相似度比较。

### 已导出的真实结果

[BM25 对照报告](../../knowledge_base/evals/results/bm25-vs-vector.md)及[完整 JSON](../../knowledge_base/evals/results/bm25-vs-vector.json)复用了已有 1000 篇资料、1528 个片段、203 道问题的向量基线，K=5、fetch_k=50、k1=1.2、b=0.75：

| 指标 | BM25 | 历史向量基线 |
|---|---:|---:|
| Hit@5 | 0.980296 | 0.990148 |
| Recall@5 | 0.748998 | 0.837536 |
| MRR@5 | 0.955255 | 0.990148 |

这是真实片段上的 BM25 检索结果，不是 mock 成绩，但仍是缩小候选库、筛选完整覆盖问题的本地对照，不能解释为完整 T2Retrieval 官方基准或最终答案正确率。不同分词策略、参数和候选库可能改变结果。

### 自动测试

```bash
uv run --frozen --no-sync --group eval python -m unittest evals.tests.test_bm25 -v
```

测试使用自己创建的临时 Qdrant、固定片段和向量排名，不读取展示快照、不请求模型。覆盖公式数值、词频饱和、长度归一化、中文分词、平分确定性、无匹配、片段预算和文档去重、全部正相关资料评分、导出内容及均值、源数据库字节不变、非法参数/损坏基线/集合不一致、查询失败和已有报告保护。

## 评估口径与后续回答评估

1. 固定文档和问题集合，记录数据文件版本或指纹、模型与处理参数。
2. 只对 corpus 构建独立评估知识库，不能把 queries 或 qrels 当作正文导入。评估前检查集合 metadata 的 `build_complete is True`，不能使用中途失败的部分库。
3. 从检索结果的 `source` 获取原始 corpus ID；同篇片段按 source 去重，Qdrant Point UUID 不能直接与 qrels.pid 比较。
4. 用问题正文执行检索，不传标准资料 ID 作为来源过滤条件。
5. 在 `fetch_k` 片段检索预算内，按每个 source 首次出现的顺序取前 K 篇文档，计算指标；不足 K 篇不补齐，报告明确记录片段预算和不足情况。
6. 按题分析未召回、排序靠后和资料不足等情况，再评估 Agent 的回答是否有证据支持。

T2Retrieval 的一个问题可能有多条相关资料。计算 Recall@K 时需要保留该题的全部正相关标注，不能只拿第一条当作完整标准。正相关文档按 ID 去重，查询等权平均；没有可评问题时报告指标为 null，模型异常不会悄悄计为零分。具体指标公式和校验规则见[评估目录说明](../../knowledge_base/evals/README.md#单题评分)。

小规模联调可以抽取问题，但候选库应包含干扰资料；只放正确答案会虚高。使用缩小的候选库得到的指标不能冒充完整数据集基准成绩。

## 检索评估与普通测试的区别

- `evals/tests/`：证明读取、关联、评分和入库逻辑正确，用小型临时数据、mock 向量和临时 Qdrant 确定性验证。
- 后续真实模型评估：测量检索效果，需要固定数据、实际 embedding 和明确指标。
- Agent 回答评估：检查答案正确性、证据支持、引用及资料不足时的行为，不等同于检索命中率。

数据加载测试通过，不代表真实模型检索效果好；预览出来的标准资料也不是模型已经搜到了这份资料。
