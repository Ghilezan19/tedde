#!/usr/bin/env bash
# Instalează serviciile Tedde în systemd, le pornește la boot și rămân repornite la crash
# (vezi deploy/tedde-*.service — Restart=always).
#
# Necesită: /etc/default/tedde cu TEDDE_ROOT setat (vezi deploy/tedde.env.example).
# Rulare: sudo bash deploy/install-systemd-services.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Rulează cu sudo (instalează unități în /etc/systemd/system)." >&2
  exit 1
fi

if [[ ! -f /etc/default/tedde ]]; then
  echo "Lipsește /etc/default/tedde. Exemplu:" >&2
  echo "  sudo cp $REPO_ROOT/deploy/tedde.env.example /etc/default/tedde" >&2
  echo "  sudo chmod 600 /etc/default/tedde" >&2
  echo "  # editează TEDDE_ROOT, PYTHON, apoi re-rulează acest script." >&2
  exit 1
fi

# shellcheck source=/dev/null
if ! (set -a; . /etc/default/tedde; set +a; : "${TEDDE_ROOT:?}"); then
  echo "Setează TEDDE_ROOT (valid) în /etc/default/tedde." >&2
  exit 1
fi

install -m 0644 "$REPO_ROOT/deploy/tedde-api.service" /etc/systemd/system/tedde-api.service
install -m 0644 "$REPO_ROOT/deploy/tedde-next.service" /etc/systemd/system/tedde-next.service

systemctl daemon-reload
systemctl enable tedde-api.service tedde-next.service
systemctl start tedde-api.service
# Pornește Next după API (After= deja definit)
systemctl start tedde-next.service

echo "OK: tedde-api și tedde-next sunt active și pornite la boot."
echo "   Status:  systemctl status tedde-api.service tedde-next.service"
echo "   Jurnal:  journalctl -u tedde-api -u tedde-next -f"
echo "Scenariu VM public + app pe acest host prin Tailscale: în /etc/default/tedde setați"
echo "  UVICORN_HOST=0.0.0.0 și NEXT_HOST=0.0.0.0, apoi: sudo systemctl restart tedde-api tedde-next"
echo "  și restringeți traficul: sudo TAILSCALE_VM_IP=... bash $REPO_ROOT/deploy/ufw-tailscale-laptop.example.sh"
echo "Pe VM: nginx + certificat, vezi nginx/video.tedde-edge-vm.conf; enable: sudo systemctl enable --now nginx"
