#!/usr/bin/env bash
# Run on the *laptop* (where Next + FastAPI run). Restricts 3000/8000 to the edge VM
# Tailscale IP only, after you set UVICORN_HOST=0.0.0.0 and NEXT_HOST=0.0.0.0 in /etc/default/tedde.
# Usage:  sudo TAILSCALE_VM_IP=100.119.3.62 bash deploy/ufw-tailscale-laptop.example.sh
# Requires: ufw, root.
set -euo pipefail

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Run with sudo" >&2
  exit 1
fi

VM_IP="${TAILSCALE_VM_IP:?Set TAILSCALE_VM_IP to the edge VM Tailscale IP (e.g. 100.119.3.62)}"
for p in 3000 8000; do
  ufw allow from "$VM_IP" to any port "$p" proto tcp
done
ufw status numbered || true
echo "Done. If ufw was inactive, run:  sudo ufw enable"
