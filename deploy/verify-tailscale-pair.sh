#!/usr/bin/env bash
# Ping laptop <-> VM over Tailscale (defaults match common layout; override via env or args).
# Example:  TAILSCALE_LAPTOP_IP=100.90.57.70 TAILSCALE_VM_IP=100.119.3.62 ./deploy/verify-tailscale-pair.sh
# Or:  ./deploy/verify-tailscale-pair.sh 100.90.57.70 100.119.3.62
set -euo pipefail

L="${1:-${TAILSCALE_LAPTOP_IP:-100.90.57.70}}"
M="${2:-${TAILSCALE_VM_IP:-100.119.3.62}}"

echo "Checking Tailscale path: laptop=$L  vm=$M"
if ! command -v ping &>/dev/null; then
  echo "ping not found" >&2
  exit 1
fi
ping -c 2 -W 3 "$L" >/dev/null
echo "  OK: can reach $L (from this host)"
ping -c 2 -W 3 "$M" >/dev/null
echo "  OK: can reach $M (from this host)"
echo "OK: both Tailscale addresses respond to ping (run on laptop and on VM to test both directions if needed)."
