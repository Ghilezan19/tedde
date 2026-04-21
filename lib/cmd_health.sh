#!/usr/bin/env bash
# shellcheck shell=bash
cmd_health() {
  require_env_file || true
  local port
  port="$(read_py_server_port)"
  export PY_SERVER_PORT="$port"
  export BASE_URL="http://127.0.0.1:${port}"

  if port_listening "$port"; then
    echo "Sursă: $BASE_URL — /api/health + /api/alpr/test (snapshot live, camera din ALPR_CAMERA din .env)"
    run_py_tool -m tools.health_pretty --full --base-url "$BASE_URL"
  else
    echo "Server oprit pe :$port — rulez probe locale (startup_check)."
    run_py_tool -m tools.health_pretty --standalone
  fi
}
