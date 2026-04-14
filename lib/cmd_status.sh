#!/usr/bin/env bash
# shellcheck shell=bash
cmd_status() {
  require_env_file || true
  local port
  port="$(read_py_server_port)"
  export PY_SERVER_PORT="$port"
  export BASE_URL="http://127.0.0.1:${port}"

  if ! port_listening "$port"; then
    echo "Server oprit (nimic pe TCP $port)."
    return 1
  fi

  echo "=== GET /health (max 10s) ==="
  curl -sS --max-time 10 "$BASE_URL/health" || echo "(eșuat)"
  echo
  echo "=== GET /api/health (max 15s) ==="
  curl -sS --max-time 15 "$BASE_URL/api/health" | head -c 4000
  echo
}
