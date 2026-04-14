#!/usr/bin/env bash
# shellcheck shell=bash
cmd_sync_env() {
  require_env_file
  run_py_tool -m tools.sync_env_from_example "$@"
}
