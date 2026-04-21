#!/usr/bin/env bash
# Instalează și configurează nginx ca reverse proxy pentru video.scoala-ai.ro
# Rulează cu: sudo bash install_nginx_proxy.sh

set -euo pipefail

DOMAIN="video.scoala-ai.ro"
BACKEND_PORT="8000"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF_SRC="$SCRIPT_DIR/nginx/${DOMAIN}.conf"
CONF_DEST="/etc/nginx/sites-available/${DOMAIN}"
CONF_LINK="/etc/nginx/sites-enabled/${DOMAIN}"

echo "=== Instalare Nginx Reverse Proxy pentru $DOMAIN ==="
echo ""

# 1. Verifică dacă rulează ca root
if [ "$EUID" -ne 0 ]; then
    echo "Trebuie rulat cu sudo: sudo bash install_nginx_proxy.sh"
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

# 4. Activare site
echo "3. Activare site..."
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
echo "Nginx proxy: $DOMAIN -> 127.0.0.1:$BACKEND_PORT"
echo ""
echo "Următorii pași:"
echo "  1. Asigură-te că serverul Python rulează pe port $BACKEND_PORT"
echo "  2. În router, forward port 80 extern -> $(hostname -I | awk '{print $1}'):80"
echo "  3. În Cloudflare, setează SSL mode: Flexible (sau Full dacă configurezi HTTPS)"
echo "  4. Testează: curl -H 'Host: $DOMAIN' http://localhost"
echo ""
echo "Pentru HTTPS direct pe server (opțional, după port forwarding):"
echo "  sudo apt install -y certbot python3-certbot-nginx"
echo "  sudo certbot --nginx -d $DOMAIN"
echo ""
