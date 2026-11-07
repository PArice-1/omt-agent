#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/lib/common.sh"

if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    printf '用法：%s [rag-mcp 参数]\n通过 stdio 等待 MCP 客户端；默认资料位于 knowledge_base/knowledge-base。\n安装：uv sync --frozen --project knowledge_base\n' "$0"
    exit 0
fi
require_command uv
[[ -x "$OMT_REPO_ROOT/knowledge_base/.venv/bin/python" ]] || fail "请先运行 uv sync --frozen --project knowledge_base。"
# 插件的相对资料和数据库路径固定基于插件目录，不受 Agent cwd 影响。
cd -- "$OMT_REPO_ROOT/knowledge_base"
exec uv run --frozen --no-sync rag-mcp "$@"
