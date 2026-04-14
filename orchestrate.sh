#!/usr/bin/env bash
# Wrapper: rulează din rădăcina repo-ului — delegă la lib/orchestrate.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/lib/orchestrate.sh" "$@"
