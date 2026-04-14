#!/usr/bin/env bash
# Oprește serverul FastAPI (uvicorn) pe portul configurat (implicit 8000).
# Folosire: ./stop.sh   sau   ./stop.sh 8000

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Citește PY_SERVER_PORT din .env dacă există, altfel 8000
PORT="${1:-}"
if [[ -z "$PORT" ]]; then
  if [[ -f "$REPO_ROOT/.env" ]]; then
    PORT="$(grep -E '^[[:space:]]*PY_SERVER_PORT=' "$REPO_ROOT/.env" | tail -1 | cut -d= -f2 | tr -d ' \r')"
  fi
  PORT="${PORT:-8000}"
fi

echo "Caut procese care ascultă pe TCP :$PORT …"

pids_listen() {
  lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null || true
}

PIDS="$(pids_listen)"
if [[ -z "$PIDS" ]]; then
  echo "Nu rulează nimic pe portul $PORT."
  exit 0
fi

echo "Opreșt PID-uri: $PIDS"
kill $PIDS 2>/dev/null || true
sleep 1

PIDS2="$(pids_listen)"
if [[ -n "$PIDS2" ]]; then
  echo "Încă activ — kill -9: $PIDS2"
  kill -9 $PIDS2 2>/dev/null || true
fi

sleep 0.5
if [[ -n "$(pids_listen)" ]]; then
  echo "Atenție: portul $PORT pare încă ocupat. Verifică manual: lsof -i :$PORT"
  exit 1
fi

echo "Server oprit (port $PORT eliberat)."
