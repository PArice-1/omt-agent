#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/lib/common.sh"

api_port="${OMT_API_PORT:-8000}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)
            printf '用法：%s [--port PORT]\n默认 OMT_API_PORT 或 8000；仅监听 127.0.0.1，保留当前工作目录。\n' "$0"
            exit 0 ;;
        --port)
            [[ $# -ge 2 ]] || fail "--port 需要参数。"
            api_port="$2"; shift 2 ;;
        *) fail "未知参数 $1；使用 --help 查看用法。" ;;
    esac
done
validate_port "$api_port"
require_backend
exec uv run --frozen --no-sync --project "$OMT_REPO_ROOT/backend" \
    uvicorn omt.api.app:create_app --factory --host 127.0.0.1 --port "$((10#$api_port))" --workers 1
