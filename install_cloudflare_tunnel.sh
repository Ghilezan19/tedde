#!/usr/bin/env bash
# Instalează cloudflared și creează tunnel pentru video.scoala-ai.ro -> localhost:8000
# Rulează cu: sudo bash install_cloudflare_tunnel.sh

set -euo pipefail

DOMAIN="video.scoala-ai.ro"
BACKEND="http://localhost:8000"
TUNNEL_NAME="tedde-video"
REAL_USER="${SUDO_USER:-$USER}"
USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

echo "=== Cloudflare Tunnel Setup pentru $DOMAIN ==="
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "Rulează cu sudo: sudo bash install_cloudflare_tunnel.sh"
    exit 1
fi

# 1. Instalare cloudflared
echo "1. Instalare cloudflared..."
if ! command -v cloudflared &> /dev/null; then
    mkdir -p --mode=0755 /usr/share/keyrings
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/cloudflared.list
    apt update
    apt install -y cloudflared
fi
echo "✓ cloudflared instalat: $(cloudflared --version | head -1)"
echo ""

# 2. Autentificare (interactiv - deschide browser)
echo "2. Autentificare Cloudflare..."
echo "Se va deschide un link în browser. Autentifică-te și selectează domeniul scoala-ai.ro"
echo ""
CERT_FILE="$USER_HOME/.cloudflared/cert.pem"
if [ ! -f "$CERT_FILE" ]; then
    sudo -u "$REAL_USER" cloudflared tunnel login
fi
echo "✓ Autentificat"
echo ""

# 3. Creare tunnel (dacă nu există)
echo "3. Creare tunnel '$TUNNEL_NAME'..."
if ! sudo -u "$REAL_USER" cloudflared tunnel list 2>/dev/null | grep -q "$TUNNEL_NAME"; then
    sudo -u "$REAL_USER" cloudflared tunnel create "$TUNNEL_NAME"
else
    echo "Tunnel '$TUNNEL_NAME' există deja"
fi

TUNNEL_ID=$(sudo -u "$REAL_USER" cloudflared tunnel list | grep "$TUNNEL_NAME" | awk '{print $1}')
echo "✓ Tunnel ID: $TUNNEL_ID"
echo ""

# 4. Config file
echo "4. Creare config..."
CONFIG_DIR="$USER_HOME/.cloudflared"
CONFIG_FILE="$CONFIG_DIR/config.yml"
cat > "$CONFIG_FILE" << EOF
tunnel: $TUNNEL_ID
credentials-file: $CONFIG_DIR/$TUNNEL_ID.json

ingress:
  - hostname: $DOMAIN
    service: $BACKEND
  - service: http_status:404
EOF
chown -R "$REAL_USER:$REAL_USER" "$CONFIG_DIR"
echo "✓ Config creat: $CONFIG_FILE"
echo ""

# 5. Rută DNS
echo "5. Configurare rută DNS..."
sudo -u "$REAL_USER" cloudflared tunnel route dns "$TUNNEL_NAME" "$DOMAIN" || echo "(ruta există deja sau trebuie ștearsă înregistrarea A existentă din Cloudflare)"
echo ""

# 6. Install ca systemd service
echo "6. Instalare ca serviciu systemd..."
cloudflared service install 2>/dev/null || true

# Copy config to /etc/cloudflared (service looks there)
mkdir -p /etc/cloudflared
cp "$CONFIG_FILE" /etc/cloudflared/config.yml
cp "$CONFIG_DIR/$TUNNEL_ID.json" /etc/cloudflared/
sed -i "s|$CONFIG_DIR|/etc/cloudflared|g" /etc/cloudflared/config.yml

systemctl enable cloudflared
systemctl restart cloudflared
echo "✓ Serviciu cloudflared activ"
echo ""

# 7. Status
echo "=== Verificare ==="
systemctl status cloudflared --no-pager | head -6
echo ""

echo "=== Setup complet ==="
echo ""
echo "Tunnel: $DOMAIN -> $BACKEND"
echo ""
echo "IMPORTANT: În Cloudflare DNS:"
echo "  - Șterge înregistrarea A video -> 185.53.199.23 (dacă există)"
echo "  - Tunnel-ul va crea automat CNAME video -> $TUNNEL_ID.cfargotunnel.com"
echo ""
echo "Testează acum: https://$DOMAIN"
