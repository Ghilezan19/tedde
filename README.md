# HiLook / Hikvision Camera Integration

Aplicație Node.js + Express pentru integrarea camerei HiLook IPC-D140HA-D-W via RTSP.

## Arhitectură

```
Browser  <-->  Express Server  <-->  ffmpeg  <-->  Camera RTSP
                  |
                  +-- /api/stream     -> RTSP -> MJPEG (live în browser)
                  +-- /api/snapshot   -> RTSP -> JPG (un singur frame)
                  +-- /api/snapshot/save -> salvează JPG pe disc
                  +-- /api/snapshots  -> listează snapshot-urile salvate
                  +-- /api/status     -> verifică dacă camera e online
                  +-- /api/info       -> informații configurare
```

## Structura Fișierelor

```
tedddde/
├── .env                 # Credențiale cameră (NU se commitează)
├── .gitignore           # Exclude .env, node_modules, snapshots
├── package.json         # Dependențe Node.js
├── server.js            # Server Express + ffmpeg wrapper
├── public/
│   └── index.html       # Frontend - live view, controls, gallery
├── snapshots/           # Folder pentru snapshot-uri salvate (auto-creat)
└── README.md            # Acest fișier
```

## Prerequisite

### 1. Node.js (v18+)
- Descarcă de la: https://nodejs.org/
- Verifică: `node --version`

### 2. ffmpeg
- **Descarcă** de la: https://www.gyan.dev/ffmpeg/builds/
  - Alege: `ffmpeg-release-essentials.zip`
- **Extrage** într-un folder, ex: `C:\ffmpeg`
- **Adaugă în PATH**:
  1. Caută "Environment Variables" în Start Menu
  2. Edit "Path" la System variables
  3. Adaugă: `C:\ffmpeg\bin`
- **Verifică**: `ffmpeg -version`

## Instalare

```bash
cd C:\Users\ghile\Desktop\tedddde
npm install
```

## Pornire

```bash
npm start
```

Deschide browserul la: **http://localhost:3000**

## Utilizare

### Live Stream în browser
1. Deschide http://localhost:3000
2. Alege calitatea (Sub/Main) și FPS-ul
3. Apasă **Start Stream**
4. Stream-ul se reconectează automat dacă pică

### Snapshot în browser
```
http://localhost:3000/api/snapshot
http://localhost:3000/api/snapshot?quality=main
http://localhost:3000/api/snapshot?quality=sub
```

### Snapshot salvat pe disc
```
http://localhost:3000/api/snapshot/save
http://localhost:3000/api/snapshot/save?quality=main&filename=intrare_principala
```

### Verificare status cameră
```
http://localhost:3000/api/status
```

## Schimbare Main Stream ↔ Sub Stream

### Din interfață
- Selectează din dropdown-ul "Calitate" → Main Stream sau Sub Stream

### Din URL (API direct)
- **Main stream** (rezoluție maximă): `?quality=main`
- **Sub stream** (rezoluție mică, mai rapid): `?quality=sub`

### Din .env
```env
RTSP_MAIN_PATH=/Streaming/channels/101
RTSP_SUB_PATH=/Streaming/channels/102
```

Pe unele camere HiLook, al treilea stream este:
```
/Streaming/channels/103
```

## Protejarea Credențialelor

1. Credențialele sunt în fișierul `.env` (exclus din git prin `.gitignore`)
2. **NU hardcoda** parola în cod
3. Parola cu `@` este encodată automat prin `encodeURIComponent()`
4. Dacă muți proiectul pe alt PC, copiază și `.env`

## Cum funcționează conversia RTSP → Browser

Browserele **NU** pot reda RTSP direct. Soluția folosită:

```
Camera RTSP  --(ffmpeg)-->  MJPEG stream  --(HTTP)-->  Browser <img>
```

- **ffmpeg** se conectează la camera RTSP via TCP
- Convertește fiecare frame în JPEG
- Le trimite ca `multipart/x-mixed-replace` (MJPEG)
- Tag-ul `<img>` din browser redă automat MJPEG

## Troubleshooting

### "ffmpeg nu este recunoscut"
- Verifică că ffmpeg e în PATH: `ffmpeg -version`
- Restart terminal după adăugarea în PATH

### "Nu se poate conecta la cameră"
- Verifică IP: `ping 192.168.100.105`
- Verifică RTSP cu VLC: `rtsp://admin:Ghilezan19%40@192.168.100.105:554/Streaming/channels/101`
- Verifică firewall-ul Windows

### Stream-ul e lent
- Folosește Sub Stream în loc de Main
- Scade FPS-ul la 2-5
- Setează o lățime mai mică (640px)

### Port 3000 ocupat
- Schimbă `SERVER_PORT` în `.env`
