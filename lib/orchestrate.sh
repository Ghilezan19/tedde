#!/usr/bin/env bash
# Orchestrator: start | stop | status | first-configuration | help
# Rulează din rădăcina repo-ului: ./lib/orchestrate.sh sau ./orchestrate.sh (wrapper în root)

set -euo pipefail

# Directorul real al acestui fișier (lib/), inclusiv dacă e symlink în root
_script_dir() {
  local path="${BASH_SOURCE[0]}"
  while [[ -L "$path" ]]; do
    local dir
    dir="$(cd -P "$(dirname "$path")" && pwd)"
    path="$(readlink "$path")"
    [[ $path == /* ]] || path="$dir/$path"
  done
  cd -P "$(dirname "$path")" && pwd
}

LIB="$(_script_dir)"
ROOT="$(cd "$LIB/.." && pwd)"
cd "$ROOT"

# shellcheck source=lib/_common.sh
source "$LIB/_common.sh"

cmd="${1:-help}"
shift || true

case "$cmd" in
  start)
    # shellcheck source=lib/cmd_start.sh
    source "$LIB/cmd_start.sh"
    cmd_start "$@"
    ;;
  stop)
    # shellcheck source=lib/cmd_stop.sh
    source "$LIB/cmd_stop.sh"
    cmd_stop "$@"
    ;;
  status)
    # shellcheck source=lib/cmd_status.sh
    source "$LIB/cmd_status.sh"
    cmd_status "$@"
    ;;
  first-configuration)
    # shellcheck source=lib/cmd_first_configuration.sh
    source "$LIB/cmd_first_configuration.sh"
    cmd_first_configuration "$@"
    ;;
  sync-env)
    # shellcheck source=lib/cmd_sync_env.sh
    source "$LIB/cmd_sync_env.sh"
    cmd_sync_env "$@"
    ;;
  health)
    # shellcheck source=lib/cmd_health.sh
    source "$LIB/cmd_health.sh"
    cmd_health "$@"
    ;;
  test-record)
    # shellcheck source=lib/cmd_test_record.sh
    source "$LIB/cmd_test_record.sh"
    cmd_test_record "$@"
    ;;
  test-send)
    # shellcheck source=lib/cmd_test_send.sh
    source "$LIB/cmd_test_send.sh"
    cmd_test_send "$@"
    ;;
  help|--help|-h)
    cat <<EOF
Tedde orchestrator (repo: $REPO_ROOT)

  ./orchestrate.sh …   sau   ./lib/orchestrate.sh …

  ./lib/orchestrate.sh start [foreground]
      Pornește uvicorn (implicit background + log logs/uvicorn.log).

  ./lib/orchestrate.sh stop [PORT]
      Oprește procesul pe PY_SERVER_PORT (sau PORT).

  ./lib/orchestrate.sh status
      Afișează /health și /api/health dacă serverul răspunde.

  ./lib/orchestrate.sh first-configuration
      Health standalone, snapshot cameră, benchmark ALPR detectoare,
      alegere interactivă model + pre-teste HTTP.

  ./lib/orchestrate.sh sync-env [--dry-run]
      Adaugă în .env cheile care există în .env_example dar lipsesc din .env.

  ./lib/orchestrate.sh health
      Tabel colorat: /api/health + ALPR live (snapshot) dacă serverul rulează;
      altfel probe locale. Verde=OK, roșu=FAIL. NO_COLOR=1 dezactivează culorile.

  ./lib/orchestrate.sh test-record
      Pornește workflow (POST /api/workflow/trigger), așteaptă finalul, verifică
      cel puțin un MP4 valid (ambele opțional; WARNING pe stderr dacă lipsește una).
      Scrie logs/test_portal_last.json. Pentru ambele camere obligatoriu: workflow_wait --strict-both.

  ./lib/orchestrate.sh test-send [EVENT_ID] [--no-sms]
      POST /api/customer-links (mock SMS dacă SMS_BACKEND=mock). Fără EVENT_ID
      citește ultimul test-record din logs/test_portal_last.json.
      Env opțional: TEST_PORTAL_OWNER_NAME, TEST_PORTAL_MECHANIC_NAME, TEST_PORTAL_PHONE.

Rulare: din rădăcina proiectului (unde este .env).
EOF
    ;;
  *)
    echo "Comandă necunoscută: $cmd  — folosește: ./lib/orchestrate.sh help" >&2
    exit 1
    ;;
esac
