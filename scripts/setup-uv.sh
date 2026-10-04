#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
command -v python3 >/dev/null || {
  cat >&2 <<'HELP'
Missing Python 3. On Ubuntu, install it and rerun this script:
  sudo apt update
  sudo apt install python3
The uv version does not require python3-pip or python3-venv.
No system packages were installed automatically.
HELP
  exit 1
}
exec python3 "$SCRIPT_DIR/lifecycle.py" setup "$@" --backend uv
