#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ -x ".venv/bin/python" ]; then
  exec .venv/bin/python -m osint_local.cli serve "$@"
fi
exec python3 -m osint_local.cli serve "$@"
