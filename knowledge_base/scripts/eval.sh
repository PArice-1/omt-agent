#!/usr/bin/env bash
# 一键执行：build_index 入库 → run 检索评分 → JSON 和 Markdown 报告。
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

usage() {
    printf '%s\n' \
        '用法：./scripts/eval.sh [选项]' \
        '  --collection NAME     新集合名，默认按时间和进程号生成' \
        '  --max-documents N     入库 corpus 前 N 条，默认 100' \
        '  --max-queries N       最多评估 N 道符合条件的问题，默认 10' \
        '  --k N                 文档 Top-K，默认 5，范围 1 到 100' \
        '  --chunk-size N        每片最大字符数，默认 1024' \
        '  --fetch-k N           检索片段数，默认 max(K, 50)，不超过 100' \
        '  --data-dir PATH       数据目录，默认 evals/data' \
        '  --db-path PATH        数据库目录，默认 DATA_DIR/storage' \
        '  --batch-size N        读取/入库批大小，默认 32' \
        '  --output PATH.json    报告路径，默认按时间命名，同时生成 .md' \
        '  -h, --help            显示帮助' \
        '' \
        '每次先构建新集合，成功后再运行评估；不会复用、覆盖或删除已有集合。' \
        '如果指定的集合已经存在，请换一个新的 --collection。'
}

fail() {
    printf '错误：%s\n' "$1" >&2
    exit 2
}

DATA_DIR="$PROJECT_ROOT/evals/data"
DB_PATH=""
COLLECTION="t2retrieval_eval_$(date +%Y%m%d_%H%M%S)_$$"
MAX_DOCUMENTS=100
MAX_QUERIES=10
K=5
CHUNK_SIZE=1024
FETCH_K=""
BATCH_SIZE=32
OUTPUT=""

while (($#)); do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --collection|--max-documents|--max-queries|--k|--chunk-size|--fetch-k|--data-dir|--db-path|--batch-size|--output)
            [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || fail "$1 缺少参数值"
            case "$1" in
                --collection) COLLECTION="$2" ;;
                --max-documents) MAX_DOCUMENTS="$2" ;;
                --max-queries) MAX_QUERIES="$2" ;;
                --k) K="$2" ;;
                --chunk-size) CHUNK_SIZE="$2" ;;
                --fetch-k) FETCH_K="$2" ;;
                --data-dir) DATA_DIR="$2" ;;
                --db-path) DB_PATH="$2" ;;
                --batch-size) BATCH_SIZE="$2" ;;
                --output) OUTPUT="$2" ;;
            esac
            shift 2 ;;
        *) fail "未知参数：$1；使用 --help 查看帮助" ;;
    esac
done

for value in "$MAX_DOCUMENTS" "$MAX_QUERIES" "$BATCH_SIZE" "$CHUNK_SIZE"; do
    [[ "$value" =~ ^[1-9][0-9]*$ ]] || fail '资料数、问题数、批大小和片段大小必须为正整数'
done
[[ "$K" =~ ^([1-9][0-9]?|100)$ ]] || fail '--k 必须为 1 到 100 的整数'
if [[ -z "$FETCH_K" ]]; then
    FETCH_K=50
    if ((K > FETCH_K)); then FETCH_K="$K"; fi
fi
[[ "$FETCH_K" =~ ^([1-9][0-9]?|100)$ ]] || fail '--fetch-k 必须为 1 到 100 的整数'
((FETCH_K >= K)) || fail '--fetch-k 不能小于 --k'
[[ -n "${COLLECTION//[[:space:]]/}" ]] || fail '集合名不能为空'
if [[ -n "$OUTPUT" ]]; then
    [[ "$OUTPUT" == *.json ]] || fail '--output 必须以 .json 结尾'
    [[ ! -e "$OUTPUT" && ! -e "${OUTPUT%.json}.md" ]] || fail '报告已存在，请换一个 --output 路径'
fi
DB_PATH="${DB_PATH:-$DATA_DIR/storage}"
COMMON=(--data-dir "$DATA_DIR" --db-path "$DB_PATH" --collection "$COLLECTION" --batch-size "$BATCH_SIZE")

printf '%s\n' "[1/2] 构建评估向量库：$COLLECTION"
uv run --group eval python -m evals.build_index "${COMMON[@]}" \
    --max-documents "$MAX_DOCUMENTS" --chunk-size "$CHUNK_SIZE"

printf '%s\n' '[2/2] 执行检索评分并生成报告'
REPORT_ARGS=()
if [[ -n "$OUTPUT" ]]; then
    REPORT_ARGS=(--output "$OUTPUT")
fi
exec uv run --group eval python -m evals.run "${COMMON[@]}" \
    --max-queries "$MAX_QUERIES" --k "$K" --fetch-k "$FETCH_K" "${REPORT_ARGS[@]}"
