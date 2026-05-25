#!/usr/bin/env bash
# Creează directoarele TLS + certificat self-signed (implicit) astfel încât
# nginx (video.tedde-auto.ro cu listen 443) treacă nginx -t.
#
#   sudo bash deploy/ensure-ssl-tedde.sh            # self-signed, valid ~2 ani
#   sudo DOMAIN=other.example.com bash deploy/ensure-ssl-tedde.sh
#
# Let's Encrypt HTTP-01 (necesită ca DNS A/AAAA să indice ACEST host + port 80 public):
#   sudo bash deploy/ensure-ssl-tedde.sh letsencrypt
#
# Din spatele NAT / fără port forward: folosește DNS challenge (ex. Cloudflare):
#   sudo CLOUDFLARE_CREDENTIALS=/path/to/cloudflare.ini bash deploy/ensure-ssl-tedde.sh letsencrypt-dns-cloudflare
# Fișier .ini: dns_cloudflare_api_token = <token cu Zone.DNS Edit>
#
# Setează opțional: CERTBOT_EMAIL=you@example.com
# Ignoră verificarea DNS (nu recomandat): SKIP_DNS_CHECK=1
#
# DNS — doar subdomeniul video (implicit video.tedde-auto.ro):
#   În panoul DNS, editezi DOAR înregistrarea pentru hostul «video» (A/AAAA către IP-ul tău).
#   NU e nevoie să schimbi apex-ul @ (tedde-auto.ro), www, mail sau alte subdomenii.
#   Scriptul și certbot folosesc numai -d "$DOMAIN" (implicit acel FQDN).
#
set -euo pipefail
[[ "${EUID:-0}" -eq 0 ]] || { echo "Rulează cu sudo." >&2; exit 1; }

### #region agent log
_DEBUG_LOG="${DEBUG_LOG:-/home/tedde-auto/work/tedde/.cursor/debug-fda54e.log}"
_agent_log() {
  local hid="$1" loc="$2" msg="$3" data="$4"
  local ts
  ts="$(date +%s)000"
  printf '%s\n' "{\"sessionId\":\"fda54e\",\"timestamp\":${ts},\"hypothesisId\":\"${hid}\",\"location\":\"${loc}\",\"message\":\"${msg}\",\"data\":${data}}" >>"$_DEBUG_LOG" 2>/dev/null || true
}
### #endregion

DOMAIN="${DOMAIN:-video.tedde-auto.ro}"
SSL_DIR="/etc/nginx/ssl/${DOMAIN}"
CERTBOT_ROOT="/var/www/certbot"
LE_LIVE="/etc/letsencrypt/live/${DOMAIN}"
MODE="${1:-selfsigned}"

install -d -m 0755 /etc/nginx/includes
install -d -m 0755 "$SSL_DIR"
install -d -m 0755 "$CERTBOT_ROOT"

if [[ "$MODE" == "selfsigned" ]]; then
  TMP="$(mktemp)"
  # SAN pentru browser-uri moderne; fără SAN unele resping certificatul
  cat >"$TMP" <<EOF
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_req
prompt = no

[req_distinguished_name]
CN = ${DOMAIN}

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = ${DOMAIN}
DNS.2 = localhost
IP.1 = 127.0.0.1
EOF
  openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
    -keyout "$SSL_DIR/privkey.pem" \
    -out "$SSL_DIR/fullchain.pem" \
    -config "$TMP" -extensions v3_req
  rm -f "$TMP"
  chmod 640 "$SSL_DIR/privkey.pem"
  chmod 644 "$SSL_DIR/fullchain.pem"
  echo "OK: self-signed la $SSL_DIR (avertisment în browser până la LE)."
  exit 0
fi

if [[ "$MODE" == "letsencrypt" ]] || [[ "$MODE" == "letsencrypt-dns-cloudflare" ]]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq certbot

  ### #region agent log
  _dig_a="$(dig +short "$DOMAIN" A 2>/dev/null | tr '\n' ' ' | sed 's/ *$//')"
  _pub="$(curl -4 -sS --max-time 6 ifconfig.me 2>/dev/null || curl -4 -sS --max-time 6 icanhazip.com 2>/dev/null || echo "")"
  _lan="$(hostname -I 2>/dev/null | awk '{print $1}')"
  _ngx="$(systemctl is-active nginx 2>/dev/null || echo unknown)"
  _l80c="$(ss -tlnp 2>/dev/null | grep -c ':80 ' || echo 0)"
  _agent_log H1 "ensure-ssl:entry" "{\"mode\":\"${MODE}\",\"domain\":\"${DOMAIN}\",\"dig_A\":\"${_dig_a}\",\"public_ipv4\":\"${_pub}\",\"lan\":\"${_lan}\"}"
  _agent_log H3 "ensure-ssl:nginx" "{\"nginx_active\":\"${_ngx}\",\"listen80_socket_lines\":\"${_l80c}\"}"
  ### #endregion

  if [[ "$MODE" == "letsencrypt" ]] && [[ -z "${SKIP_DNS_CHECK:-}" ]]; then
    _match=0
    for ip in $_dig_a; do
      [[ "$ip" == "$_pub" ]] && _match=1
    done
    if [[ "$_match" -ne 1 ]] || [[ -z "$_pub" ]]; then
      ### #region agent log
      _agent_log H1 "ensure-ssl:preflight_fail" "{\"reason\":\"dns_A_does_not_match_this_public_ip\",\"dig_A\":\"${_dig_a}\",\"expected_public\":\"${_pub}\"}"
      ### #endregion
      echo "" >&2
      echo "=== Preflight Let's Encrypt (HTTP-01) — oprit aici ===" >&2
      echo "Subdomeniu verificat: ${DOMAIN}" >&2
      echo "" >&2
      echo "— Ce înseamnă valorile (sunt diferite cu intent):" >&2
      echo "  • DNS (dig): ${_dig_a:-<gol>}  ← unde se duce LUMEA când scrie ${DOMAIN} în browser / LE." >&2
      echo "  • IP public al ACESTUI laptop (ifconfig): ${_pub:-<necunoscut>}  ← doar conexiunea ta de acasă." >&2
      echo "  Dacă ai cerut în DNS ca «video» să pointeze spre un SERVER (ex. 185.x), e normal ca" >&2
      echo "  dig și ifconfig să difere: nu e „greșit”, înseamnă că serviciul trebuie pe server, nu pe laptop." >&2
      echo "" >&2
      echo "Let’s Encrypt (HTTP-01) descarcă de pe IP-urile din DNS, nu de pe laptop dacă DNS nu e laptopul." >&2
      echo "" >&2
      echo "Ce faci în practică (alege una):" >&2
      echo "  1) Hostezi pe SERVERUL din DNS (${_dig_a}): conectează-te acolo (SSH), pune nginx+certbot" >&2
      echo "     și rulează acolo: sudo bash $0 letsencrypt  (sau certbot pe acel host)." >&2
      echo "  2) Hostezi PE ACEST laptop: în DNS, A pentru «video» → ${_pub}; router port forward 80/443 → ${_lan}." >&2
      echo "  3) Certificat de pe laptop fără HTTP pe server: DNS challenge (ex. Cloudflare):" >&2
      echo "     sudo CLOUDFLARE_CREDENTIALS=/path/to/cf.ini bash $0 letsencrypt-dns-cloudflare" >&2
      echo "  4) Forțez fără verificare (risc): SKIP_DNS_CHECK=1 sudo bash $0 letsencrypt" >&2
      exit 2
    fi
    ### #region agent log
    _agent_log H1 "ensure-ssl:preflight_ok" "{\"dig_A\":\"${_dig_a}\",\"public_ipv4\":\"${_pub}\"}"
    ### #endregion
  fi

  email_args=()
  if [[ -n "${CERTBOT_EMAIL:-}" ]]; then
    email_args=(--email "$CERTBOT_EMAIL" --no-eff-email)
  else
    email_args=(--register-unsafely-without-email)
  fi

  if [[ "$MODE" == "letsencrypt-dns-cloudflare" ]]; then
    [[ -n "${CLOUDFLARE_CREDENTIALS:-}" ]] || { echo "Setează CLOUDFLARE_CREDENTIALS=/cale/către/cloudflare.ini" >&2; exit 1; }
    apt-get install -y -qq python3-certbot-dns-cloudflare
    ### #region agent log
    _agent_log H6 "ensure-ssl:certbot_cf" "{\"domain\":\"${DOMAIN}\"}"
    ### #endregion
    certbot certonly --non-interactive --agree-tos \
      "${email_args[@]}" \
      --dns-cloudflare \
      --dns-cloudflare-credentials "$CLOUDFLARE_CREDENTIALS" \
      -d "$DOMAIN"
  else
    ### #region agent log
    _agent_log H4 "ensure-ssl:certbot_webroot" "{\"webroot\":\"${CERTBOT_ROOT}\",\"domain\":\"${DOMAIN}\"}"
    ### #endregion
    certbot certonly --webroot -w "$CERTBOT_ROOT" -d "$DOMAIN" \
      --non-interactive --agree-tos \
      "${email_args[@]}"
  fi

  ### #region agent log
  _agent_log H4 "ensure-ssl:certbot_ok" "{\"domain\":\"${DOMAIN}\"}"
  ### #endregion
  install -d -m 0755 "$SSL_DIR"
  ln -sfn "$LE_LIVE/fullchain.pem" "$SSL_DIR/fullchain.pem"
  ln -sfn "$LE_LIVE/privkey.pem" "$SSL_DIR/privkey.pem"
  echo "OK: certificat Let's Encrypt; symlink în $SSL_DIR"
  if command -v nginx &>/dev/null; then
    nginx -t && systemctl reload nginx
  fi
  exit 0
fi

echo "Utilizare: $0 [selfsigned|letsencrypt|letsencrypt-dns-cloudflare]" >&2
exit 1
