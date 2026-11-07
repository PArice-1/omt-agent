#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/lib/common.sh"

require_command python3
exec python3 "$OMT_REPO_ROOT/scripts/run_web.py" "$@"
