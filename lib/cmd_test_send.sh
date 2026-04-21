#!/usr/bin/env bash
# shellcheck shell=bash

cmd_test_send() {
  require_env_file || exit 1

  local port
  port="$(read_py_server_port)"
  export PY_SERVER_PORT="$port"
  export BASE_URL="http://127.0.0.1:${port}"

  if ! port_listening "$port"; then
    echo "Serverul nu ascultă pe :$port — pornește cu ./lib/orchestrate.sh start" >&2
    exit 1
  fi

  run_py_tool -m tools.test_portal_send --base-url "$BASE_URL" --repo-root "$REPO_ROOT" "$@"
}
