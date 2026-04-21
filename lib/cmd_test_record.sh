#!/usr/bin/env bash
# shellcheck shell=bash

read_recording_duration_seconds() {
  local sec=60
  if [[ -f "$ENV_FILE" ]]; then
    local line
    line="$(grep -E '^[[:space:]]*RECORDING_DURATION_SECONDS=' "$ENV_FILE" | tail -1 || true)"
    if [[ -n "$line" ]]; then
      local v="${line#*=}"
      v="$(echo "$v" | tr -d ' \r\"')"
      if [[ "$v" =~ ^[0-9]+$ ]]; then
        sec="$v"
      fi
    fi
  fi
  echo "$sec"
}

read_events_dir_abs() {
  local rel="./events"
  if [[ -f "$ENV_FILE" ]]; then
    local line
    line="$(grep -E '^[[:space:]]*EVENTS_DIR=' "$ENV_FILE" | tail -1 || true)"
    if [[ -n "$line" ]]; then
      rel="${line#*=}"
      rel="$(echo "$rel" | tr -d '\r\"' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    fi
  fi
  if [[ "$rel" == /* ]]; then
    echo "$rel"
  else
    rel="${rel#./}"
    echo "$REPO_ROOT/$rel"
  fi
}

cmd_test_record() {
  require_env_file || exit 1

  local port
  port="$(read_py_server_port)"
  export PY_SERVER_PORT="$port"
  export BASE_URL="http://127.0.0.1:${port}"

  if ! port_listening "$port"; then
    echo "Serverul nu ascultă pe :$port — pornește cu ./lib/orchestrate.sh start" >&2
    exit 1
  fi

  local resp
  resp="$(mktemp)"

  local http
  http="$(curl -sS -o "$resp" -w "%{http_code}" -X POST "$BASE_URL/api/workflow/trigger" --max-time 30)" || true
  if [[ "$http" != "200" ]]; then
    echo "POST /api/workflow/trigger a eșuat (HTTP $http):" >&2
    cat "$resp" >&2 || true
    rm -f "$resp"
    exit 1
  fi

  if ! run_py_tool -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get(\"success\") else 1)" "$resp"; then
    echo "Trigger respins (success=false):" >&2
    cat "$resp" >&2 || true
    rm -f "$resp"
    exit 1
  fi
  rm -f "$resp"

  local dur wait_sec events_abs
  dur="$(read_recording_duration_seconds)"
  wait_sec=$((dur + 90))
  events_abs="$(read_events_dir_abs)"

  mkdir -p "$REPO_ROOT/logs"
  local state_path="$REPO_ROOT/logs/test_portal_last.json"

  echo "Aștept finalizarea workflow (max ${wait_sec}s, RECORDING_DURATION_SECONDS=$dur)…"
  if ! run_py_tool -m tools.workflow_wait \
    --base-url "$BASE_URL" \
    --timeout "$wait_sec" \
    --validate-under "$events_abs" \
    --write-state "$state_path"; then
    echo "workflow_wait a eșuat — vezi mesajele de mai sus." >&2
    exit 1
  fi

  echo ""
  echo "State: $state_path"
  local ef plate
  ef="$(run_py_tool -c "import json,sys; print(json.load(open(sys.argv[1]))[\"event_id\"])" "$state_path")"
  plate="$(run_py_tool -c "import json,sys; print(json.load(open(sys.argv[1]))[\"license_plate\"])" "$state_path")"
  echo "Eveniment: $ef"
  echo "Număr:   $plate"
  echo "Fișiere: $events_abs/$ef/camera1.mp4"
  echo "         $events_abs/$ef/camera2.mp4"
  echo ""
  echo "Link portal (mock SMS): ./lib/orchestrate.sh test-send"
}
