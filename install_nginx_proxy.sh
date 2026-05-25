#!/usr/bin/env bash
# Instalează și configurează nginx ca reverse proxy.
#
# Domeniul implicit: video.scoala-ai.ro. Pentru video.tedde-auto.ro (config în
# repo: nginx/video.tedde-auto.ro.conf), rulează de exemplu:
#   DOMAIN=video.tedde-auto.ro sudo -E bash install_nginx_proxy.sh
#
# DNS: înainte ca numele de host să răspundă de pe acest server, setează
# înregistrări A/AAAA spre IP-ul public al mașinii (nu doar alte hosturi random).
# SSL/Cloudflare: alege modul (Flexible vs Full) în funcție de certificatul de pe
# origin; vezi comentariile de la finalul acestui script.

set -euo pipefail

DOMAIN="${DOMAIN:-video.scoala-ai.ro}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
NEXT_PORT="${NEXT_PORT:-3000}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF_SRC="$SCRIPT_DIR/nginx/${DOMAIN}.conf"
CONF_DEST="/etc/nginx/sites-available/${DOMAIN}"
CONF_LINK="/etc/nginx/sites-enabled/${DOMAIN}"

echo "=== Instalare Nginx Reverse Proxy pentru $DOMAIN ==="
echo ""

# 1. Verifică dacă rulează ca root
if [ "$EUID" -ne 0 ]; then
    echo "Trebuie rulat cu sudo, ex: sudo bash install_nginx_proxy.sh"
    echo "Sau: DOMAIN=video.tedde-auto.ro sudo -E bash install_nginx_proxy.sh"
    exit 1
fi

# 2. Instalare nginx
echo "1. Instalare nginx..."
apt update
apt install -y nginx
echo "✓ Nginx instalat"
echo ""

# 3. Copiere config
echo "2. Copiere config pentru $DOMAIN..."
if [ ! -f "$CONF_SRC" ]; then
    echo "EROARE: Nu găsesc $CONF_SRC"
    exit 1
fi
cp "$CONF_SRC" "$CONF_DEST"
echo "✓ Config copiat în $CONF_DEST"
echo ""

# 3b. Fragmente nginx (location-uri partajate pentru video.tedde-auto.ro)
INCLUDES_SRC="$SCRIPT_DIR/nginx/includes"
INCLUDES_DEST="/etc/nginx/includes"
if [[ -d "$INCLUDES_SRC" ]]; then
  echo "2b. Fragmente include în $INCLUDES_DEST ..."
  install -d -m 0755 "$INCLUDES_DEST"
  shopt -s nullglob
  for f in "$INCLUDES_SRC"/*.conf; do
    [[ -f "$f" ]] || continue
    cp -a "$f" "$INCLUDES_DEST/"
    echo "  $(basename "$f")"
  done
  shopt -u nullglob
  echo "✓ Includes actualizate"
  echo ""
fi

# 3c. TLS pentru domeniul Tedde (443 + fișiere PEM; fără asta nginx -t eșuează)
if [[ "$DOMAIN" == "video.tedde-auto.ro" ]] && [[ -x "$SCRIPT_DIR/deploy/ensure-ssl-tedde.sh" ]]; then
  echo "2c. Certificat TLS (self-signed inițial; poți trece la LE: deploy/ensure-ssl-tedde.sh letsencrypt)..."
  bash "$SCRIPT_DIR/deploy/ensure-ssl-tedde.sh" selfsigned
  echo "✓ TLS"
  echo ""
fi

# 4. Activare site
echo "3. Activare site (symlink)..."
ln -sf "$CONF_DEST" "$CONF_LINK"
echo "✓ Site activat"
echo ""

# 5. Dezactivare default (opțional)
if [ -L /etc/nginx/sites-enabled/default ]; then
    echo "4. Dezactivare site default..."
    rm /etc/nginx/sites-enabled/default
    echo "✓ Default dezactivat"
    echo ""
fi

# 6. Test config
echo "5. Test config nginx..."
nginx -t
echo "✓ Config valid"
echo ""

# 7. Reload nginx
echo "6. Reload nginx..."
systemctl enable nginx
systemctl reload nginx || systemctl restart nginx
echo "✓ Nginx pornit și activ"
echo ""

# 8. Firewall (dacă e activ)
if command -v ufw &> /dev/null; then
    echo "7. Configurare firewall..."
    ufw allow 'Nginx Full' 2>/dev/null || true
    echo "✓ Firewall configurat"
    echo ""
fi

# 9. Verificare
echo "=== Verificare finală ==="
systemctl status nginx --no-pager | head -5
echo ""
echo "Porturi deschise:"
ss -tlnp | grep -E ':(80|443|8000)' || true
echo ""

echo "=== Setup complet ==="
echo ""
echo "Nginx: $DOMAIN -> FastAPI 127.0.0.1:$BACKEND_PORT, Next.js 127.0.0.1:$NEXT_PORT"
echo ""
echo "Următorii pași:"
echo "  1. Pornește FastAPI pe $BACKEND_PORT și Next (pnpm start) pe $NEXT_PORT; vezi deploy/tedde-*.service"
echo "  2. Asigură-te că DNS (A/AAAA) pentru $DOMAIN indică acest server"
echo "  3. În router, forward port 80 extern -> $(hostname -I | awk '{print $1}'):80"
echo "  4. În Cloudflare, setează SSL mode: Flexible (sau Full dacă configurezi HTTPS pe origin)"
echo "  5. Test: curl -sI -H 'Host: $DOMAIN' http://127.0.0.1/ | head -1"
echo ""
echo "HTTPS (video.tedde-auto.ro): cert self-signed la instalare; pentru Let's Encrypt:"
echo "  sudo bash deploy/ensure-ssl-tedde.sh letsencrypt   # după ce DNS+port 80 merg"
echo ""
