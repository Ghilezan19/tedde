# Ghid Conectare Remote de pe Alt Laptop

## Metoda 1: SSH prin Tailscale (Recomandat - Rapid și Sigur)

### Pasul 1: Instalează Tailscale pe laptopul de pe care te conectezi

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

- Deschide link-ul din browser și autentifică-te cu același cont

### Pasul 2: Află IP-ul Tailscale al serverului Ubuntu

Pe serverul Ubuntu:
```bash
tailscale ip -4
```

Vei vedea un IP de forma `100.x.x.x`

### Pasul 3: Conectare prin SSH

De pe laptopul tău:
```bash
ssh nume_user@100.x.x.x
```

Unde:
- `nume_user` = user-ul de pe Ubuntu (rulează `whoami` pe server pentru a afla)
- `100.x.x.x` = IP-ul Tailscale de la Pasul 2

### Pasul 4: Configurare chei SSH (opțional - pentru a nu mai introduce parola)

Pe laptopul tău:
```bash
ssh-keygen -t ed25519
ssh-copy-id nume_user@100.x.x.x
```

De acum poți intra fără parolă:
```bash
ssh nume_user@100.x.x.x
```

### Pasul 5: Activează Tailscale SSH (opțional - mai simplu)

Pe serverul Ubuntu:
```bash
sudo tailscale set --ssh
```

Asta permite să te conectezi direct prin Tailscale fără configurări suplimentare.

---

## Metoda 2: AnyDesk (Pentru Desktop Grafic)

### Pasul 1: Instalează AnyDesk pe laptopul tău

Descarcă de pe https://anydesk.com/en/downloads/downloads-windows

### Pasul 2: Află ID-ul AnyDesk al serverului Ubuntu

Pe serverul Ubuntu, deschide AnyDesk și vezi ID-ul (format: 9-cifre)

### Pasul 3: Conectare prin AnyDesk

1. Deschide AnyDesk pe laptop
2. Introdu ID-ul serverului Ubuntu
3. Apasă "Connect"
4. Introdu parola de Unattended Access (cea setată pe server)

---

## Verificare Servicii pe Server

Pe serverul Ubuntu, verifică că totul rulează:

```bash
# Verifică SSH
systemctl status ssh

# Verifică Tailscale
systemctl status tailscaled
tailscale status

# Verifică AnyDesk
systemctl status anydesk
```

---

## Recomandare de Utilizare

- **90% din timp**: Folosește **SSH prin Tailscale** - rapid, stabil, consum minim
- **Când ai nevoie de GUI**: Folosește **AnyDesk** - vezi desktop-ul complet

Ambele metode pot fi folosite simulta și rămân active în background.

---

## Troubleshooting

### SSH nu merge
```bash
# Pe server, verifică dacă SSH rulează
sudo systemctl restart ssh
sudo ufw allow 22
```

### Tailscale nu se conectează
```bash
# Pe server
sudo tailscale up --reset
sudo tailscale up
```

### AnyDesk nu pornește
```bash
sudo systemctl restart anydesk
sudo anydesk --service
```
