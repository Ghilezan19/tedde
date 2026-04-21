#!/bin/bash

# Script pentru instalare SSH, Tailscale și AnyDesk pe Ubuntu
# Rulează cu: sudo bash install_remote_access.sh

set -e

echo "=== Instalare SSH, Tailscale și AnyDesk ==="
echo ""

# Partea 1: SSH
echo "1. Instalare și configurare SSH..."
sudo apt update
sudo apt install -y openssh-server
sudo systemctl enable ssh
sudo systemctl start ssh
sudo systemctl status ssh --no-pager
echo "✓ SSH instalat și pornit"
echo ""

# Partea 2: Tailscale
echo "2. Instalare Tailscale..."
curl -fsSL https://tailscale.com/install.sh | sh
echo "✓ Tailscale instalat"
echo ""
echo "IMPORTANT: Rulează 'sudo tailscale up' și urmează instrucțiunile din browser pentru autentificare"
echo ""

# Partea 3: AnyDesk
echo "3. Instalare AnyDesk..."
echo "Adăugare repository AnyDesk oficial..."
wget -qO - https://keys.anydesk.com/repos/DEB-GPG-KEY | sudo apt-key add -
echo "deb http://deb.anydesk.com/ all main" | sudo tee /etc/apt/sources.list.d/anydesk-stable.list
sudo apt update
sudo apt install -y anydesk
sudo systemctl enable anydesk
sudo systemctl start anydesk
sudo systemctl status anydesk --no-pager
echo "✓ AnyDesk instalat și pornit"
echo ""

# Verificare finală
echo "=== Verificare servicii ==="
echo "SSH:"
systemctl status ssh --no-pager | head -3
echo ""
echo "Tailscale:"
systemctl status tailscaled --no-pager | head -3
echo ""
echo "AnyDesk:"
systemctl status anydesk --no-pager | head -3
echo ""

echo "=== Informații utile ==="
echo "User curent: $(whoami)"
echo "IP local: $(hostname -I | awk '{print $1}')"
echo ""
echo "Următorii pași:"
echo "1. Rulează: sudo tailscale up"
echo "2. Autentifică device-ul în browser"
echo "3. Rulează: tailscale ip -4  (pentru a vedea IP-ul Tailscale)"
echo "4. Configurează AnyDesk pentru acces neasistat (setează parolă)"
echo ""
echo "Consultă ghidul CONECTARE_REMOTE.md pentru instrucțiuni de conectare de pe alt laptop"
