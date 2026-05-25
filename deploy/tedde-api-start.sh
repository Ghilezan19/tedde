#!/usr/bin/env bash
# Uvicorn FastAPI for Tedde. Requires TEDDE_ROOT and PYTHON in environment
# (see /etc/default/tedde from deploy/tedde.env.example).
set -euo pipefail
: "${TEDDE_ROOT:?Set TEDDE_ROOT (e.g. in /etc/default/tedde)}"
py="${PYTHON:-$TEDDE_ROOT/.venv/bin/python}"
if [[ ! -x "$py" ]]; then
  echo "No executable PYTHON at $py; install deps or set PYTHON in /etc/default/tedde" >&2
  exit 1
fi
cd "$TEDDE_ROOT/py_backend"
host="${UVICORN_HOST:-127.0.0.1}"
port="${UVICORN_PORT:-8000}"
exec "$py" -m uvicorn main:app --host "$host" --port "$port"
