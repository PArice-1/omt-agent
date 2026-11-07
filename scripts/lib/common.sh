#!/usr/bin/env bash

# 仅定位安装目录；调用者的 cwd 留给 Agent 作为工作目录。
OMT_REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly OMT_REPO_ROOT

fail() {
    printf '错误：%s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "缺少 $1，请先安装后重试。"
}

require_backend() {
    require_command uv
    [[ -x "$OMT_REPO_ROOT/backend/.venv/bin/python" ]] || fail "后端依赖未安装，请运行 scripts/setup.sh。"
}

validate_port() {
    [[ "$1" =~ ^[0-9]{1,5}$ ]] || fail "端口必须是 1 到 65535 的整数。"
    (( 10#$1 >= 1 && 10#$1 <= 65535 )) || fail "端口必须是 1 到 65535 的整数。"
}
