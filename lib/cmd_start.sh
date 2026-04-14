#!/usr/bin/env bash
# shellcheck shell=bash
cmd_start() {
  require_env_file
  local mode="${1:-background}"
  local py
  py="$(python_exec)"
  export_py_backend_path

  mkdir -p "$REPO_ROOT/logs"
  local logf="$REPO_ROOT/logs/uvicorn.log"
  local port
  port="$(read_py_server_port)"

  if port_listening "$port"; then
    echo "Serverul pare deja activ pe portul $port ($BASE_URL)." >&2
    return 0
  fi

  cd "$PY_BACKEND"
  if [[ "$mode" == "foreground" ]]; then
    echo "Pornire uvicorn (foreground) pe :$port …"
    exec "$py" -m uvicorn main:app --host 0.0.0.0 --port "$port"
  fi

  echo "Pornire uvicorn (background) pe :$port — log: $logf"
  nohup "$py" -m uvicorn main:app --host 0.0.0.0 --port "$port" >>"$logf" 2>&1 &
  echo "PID: $!"
}
