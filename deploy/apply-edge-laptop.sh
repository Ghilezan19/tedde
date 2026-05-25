#!/usr/bin/env bash
# Aplică /etc/default/tedde, instalează systemd, UFW, verifică ping Tailscale.
# Rulare:  cd repo && bash deploy/apply-edge-laptop.sh
# Cere parolă sudo o dată.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${EUID:-0}" -ne 0 ]]; then
  exec sudo env TEDDE_GIT_ROOT="$ROOT" bash "$0" "$@"
fi
ROOT="${TEDDE_GIT_ROOT:-$ROOT}"

echo "==> /etc/default/tedde (edge + bind 0.0.0.0)"
install -m 600 -T "$ROOT/deploy/tedde.default.edge" /etc/default/tedde

echo "==> Systemd: tedde-api + tedde-next"
bash "$ROOT/deploy/install-systemd-services.sh"

set -a
# shellcheck source=/dev/null
. /etc/default/tedde
set +a
echo "==> UFW: allow 3000,8000 from VM (Tailscale) only (TAILSCALE_VM_IP=$TAILSCALE_VM_IP)"
bash "$ROOT/deploy/ufw-tailscale-laptop.example.sh"

echo "==> Verificare ping Tailscale (folosește IP-urile din plan; editează dacă ți s-au schimbat)"
L="${TAILSCALE_LAPTOP_IP:-100.90.57.70}"
M="${TAILSCALE_VM_IP:-100.119.3.62}"
if bash "$ROOT/deploy/verify-tailscale-pair.sh" "$L" "$M"; then
  : ok
else
  echo "Avertisment: ping a eșuat (Tailscale pornit? IP-uri corecte?)" >&2
fi

echo "Gata. Status:  sudo systemctl status tedde-api tedde-next"
echo "Jurnal:       sudo journalctl -u tedde-api -u tedde-next -n 30 --no-pager"
