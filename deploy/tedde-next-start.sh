#!/usr/bin/env bash
set -euo pipefail
: "${TEDDE_ROOT:?Set TEDDE_ROOT (e.g. in /etc/default/tedde)}"
export NODE_ENV=production
export BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"
export HOSTNAME="${NEXT_HOST:-127.0.0.1}"
export PORT="${NEXT_PORT:-3000}"
cd "$TEDDE_ROOT/frontend"
if command -v pnpm &>/dev/null; then
  exec pnpm start
elif [[ -n "${PNPM:-}" && -x "${PNPM}" ]]; then
  exec "$PNPM" start
else
  exec npm run start
fi
