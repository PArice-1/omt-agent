#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/lib/common.sh"

if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    printf '用法：%s [--tui | --plain]\n默认启动 TUI，保留当前工作目录；其余参数交给 omt。\n' "$0"
    exit 0
fi
require_backend
exec uv run --frozen --no-sync --project "$OMT_REPO_ROOT/backend" omt "$@"
