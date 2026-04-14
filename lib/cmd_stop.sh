#!/usr/bin/env bash
# shellcheck shell=bash
cmd_stop() {
  local port="${1:-$PY_SERVER_PORT}"
  bash "$PY_BACKEND/stop.sh" "$port"
}
