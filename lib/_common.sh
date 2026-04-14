#!/usr/bin/env bash
# Shared helpers for lib/orchestrate.sh — source from repo root.

set -euo pipefail

# Directory containing this file (lib/)
LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$LIB_DIR/.." && pwd)"
export REPO_ROOT
export LIB_DIR

PY_BACKEND="$REPO_ROOT/py_backend"
export PY_BACKEND

ENV_FILE="$REPO_ROOT/.env"
export ENV_FILE

# Prefer project venv, else python3 on PATH
python_exec() {
  if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    echo "$REPO_ROOT/.venv/bin/python"
  elif [[ -x "$REPO_ROOT/venv/bin/python" ]]; then
    echo "$REPO_ROOT/venv/bin/python"
  else
    command -v python3
  fi
}

# Read PY_SERVER_PORT from .env (no secrets printed)
read_py_server_port() {
  local port="8000"
  if [[ -f "$ENV_FILE" ]]; then
    local line
    line="$(grep -E '^[[:space:]]*PY_SERVER_PORT=' "$ENV_FILE" | tail -1 || true)"
    if [[ -n "$line" ]]; then
      port="${line#*=}"
      port="$(echo "$port" | tr -d ' \r\"')"
    fi
  fi
  echo "$port"
}

export PY_SERVER_PORT="${PY_SERVER_PORT:-$(read_py_server_port)}"
export BASE_URL="http://127.0.0.1:${PY_SERVER_PORT}"

require_env_file() {
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "Lipsește $ENV_FILE — copiază din .env_example și completează IP-urile camerelor." >&2
    return 1
  fi
}

# PYTHONPATH so `python -m tools.*` resolves from py_backend
export_py_backend_path() {
  export PYTHONPATH="$PY_BACKEND${PYTHONPATH:+:$PYTHONPATH}"
}

run_py_tool() {
  export_py_backend_path
  local py
  py="$(python_exec)"
  (cd "$REPO_ROOT" && "$py" "$@")
}

port_listening() {
  local port="${1:-$PY_SERVER_PORT}"
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti "tcp:$port" -sTCP:LISTEN >/dev/null 2>&1
  else
    # Fallback: bash /dev/tcp (may be disabled on some systems)
    (echo >/dev/tcp/127.0.0.1/"$port") >/dev/null 2>&1 || return 1
  fi
}

curl_health() {
  curl -sS --max-time 10 -f "$BASE_URL/health" || return 1
}

wait_for_health() {
  local max="${1:-45}"
  local i=0
  while (( i < max )); do
    if curl -sS --max-time 5 -f "$BASE_URL/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    ((i++)) || true
  done
  return 1
}
