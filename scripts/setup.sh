#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/lib/common.sh"

with_knowledge=false
case "${1:-}" in
    --help|-h)
        printf '用法：%s [--with-knowledge-base]\n默认安装 backend 和 frontend；可选安装知识库插件。\n' "$0"
        exit 0 ;;
    --with-knowledge-base) with_knowledge=true; shift ;;
esac
[[ $# -eq 0 ]] || fail "未知参数；使用 --help 查看用法。"
require_command uv
require_command node
require_command npm
node -e 'const [major,minor]=process.versions.node.split(".").map(Number); if(major<22 || (major===22 && minor<19)){console.error("需要 Node.js 22.19+");process.exit(1)}'
uv sync --frozen --project "$OMT_REPO_ROOT/backend"
npm ci --prefix "$OMT_REPO_ROOT/frontend"
if [[ "$with_knowledge" == true ]]; then
    uv sync --frozen --project "$OMT_REPO_ROOT/knowledge_base"
fi
printf '依赖已安装。知识库不会自动启用，接入方式见 docs/knowledge_base/plugin.md。\n'
