# Tedde Unified Camera Service

Serviciu Python-only bazat pe FastAPI pentru:
- dashboard web
- stream live MJPEG
- snapshot-uri si inregistrari
- control PTZ / audio / image settings
- workflow unic pentru browser + ESP
- ALPR integrat la startul workflow-ului
- portal public pentru clienti cu quiz + video share
- trimitere SMS prin backend `mock` sau `custom_http`

## Arhitectura

```text
Browser / ESP  <-->  FastAPI (Python)  <-->  ffmpeg  <-->  Camere RTSP
                        |
                        +-- /api/stream
                        +-- /api/snapshot
                        +-- /api/record/*
                        +-- /api/workflow/*
                        +-- /api/events
                        +-- /api/customer-links
                        +-- /ws/audio
                        +-- /verificare/{token}
```

Nu mai exista runtime Node.js. `server.js`, `package.json` si `package-lock.json`
nu mai sunt necesare in deploy.

## Structura

```text
tedde/
├── .env
├── .env_example
├── public/
│   └── index.html
├── py_backend/
│   ├── main.py
│   ├── requirements.txt
│   ├── camera/
│   ├── routes/
│   └── services/
├── snapshots/
├── recordings/
├── events/
└── README.md
```

## Cerinte

### 1. Python 3.11+

Verifica:

```bash
python3 --version
```

### 2. ffmpeg

Verifica:

```bash
ffmpeg -version
```

Daca `ffmpeg` nu este in PATH, seteaza calea completa in `.env` la `FFMPEG_PATH`.

## Instalare

Din root-ul repo-ului:

```bash
cd /Users/maleticimiroslav/CamereTedde/tedde

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r py_backend/requirements.txt
cp .env_example .env
```

Completeaza apoi `.env` cu:
- `PY_SERVER_PORT`
- `FFMPEG_PATH`
- credentialele camerelor
- `RECORDING_DURATION_SECONDS`
- optional `ESP_COUNTDOWN_SECONDS`
- `EVENTS_DIR`
- `ALPR_ENABLED`
- `ALPR_CAMERA`
- `PUBLIC_BASE_URL`
- `CUSTOMER_PORTAL_DB_PATH`
- `SMS_BACKEND`

## Pornire

```bash
cd /Users/maleticimiroslav/CamereTedde/tedde/py_backend
source ../.venv/bin/activate
python3 main.py
```

Alternativ, fara reload:

```bash
cd /Users/maleticimiroslav/CamereTedde/tedde/py_backend
source ../.venv/bin/activate
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
```

## Acces

- UI local: `http://localhost:8000`
- Health: `http://localhost:8000/health`
- Detailed health: `http://localhost:8000/api/health`
- ESP config: `http://localhost:8000/api/esp/config`

ESP-ul si browserul trebuie sa foloseasca acelasi host si acelasi port.

## Workflow

Trigger din browser:

```bash
POST /api/workflow/trigger
Content-Type: application/json

{"duration_seconds": 30}
```

(`duration_seconds` este opțional, 5–600; dacă lipsește, se folosește `RECORDING_DURATION_SECONDS` din `.env`.)

Trigger compatibil ESP:

```bash
POST /counter-start
```

Status workflow:

```bash
GET /api/workflow/status
GET /api/events
GET /api/events/{event_id}
```

La startul workflow-ului:
1. se încearcă înregistrările pe camera 1 și 2 (dacă ffmpeg nu pornește pe o cameră, cealaltă continuă)
2. se face snapshot din camera configurată pentru ALPR
3. rulează ALPR
4. se creează folderul evenimentului
5. se salvează `alpr_start.jpg`, `alpr.json` și câte fișiere `camera*.mp4` sunt valide (minim ~8 KB; o cameră poate lipsi)

În UI: tab **„Test”** în panoul din dreapta (`public/index.html`) — countdown, preview clipuri, trimitere link + previzualizare SMS.

Status workflow (`GET /api/workflow/status`, câmpul `last_event`) include `recordings`, `recording_warnings`, `recording_partial` după finalizare.

## Portal client + SMS

### 1. Ia `event_id`

Operatorul alege evenimentul din:

```bash
curl http://localhost:8000/api/events
```

`event_id` este chiar numele folderului din `events/`, de forma:

```text
B123ABC_2026-04-14T12-30-00Z
```

### 2. Creeaza linkul public

```bash
curl -X POST http://localhost:8000/api/customer-links \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "B123ABC_2026-04-14T12-30-00Z",
    "license_plate": "B123ABC",
    "owner_name": "Ion Popescu",
    "mechanic_name": "Mihai",
    "phone_number": "+40744111222",
    "send_sms": true
  }'
```

Raspunsul intoarce:
- `link_id`
- `token`
- `public_url`
- `sms_status`
- `sms_preview` (textul SMS, inclusiv URL)
- `warnings`, `recording_partial` dacă există o singură înregistrare video validă
- `expires_at`

### 3. Re-trimite acelasi link

```bash
curl -X POST http://localhost:8000/api/customer-links/12/resend
```

Se reutilizeaza acelasi token; nu se genereaza alt link.

### 4. Public URL

Linkul public este construit strict din `PUBLIC_BASE_URL` + `PORTAL_PATH_PREFIX`.
Pentru mutare pe domeniu sau subdomeniu nou schimbi doar:

```env
PUBLIC_BASE_URL=https://portal.exemplu.ro
PORTAL_PATH_PREFIX=/verificare
```

Nu exista auto-detect dupa host-ul request-ului.

### 5. Provider SMS

Default local:

```env
SMS_BACKEND=mock
```

Provider HTTP custom:

```env
SMS_BACKEND=custom_http
SMS_HTTP_URL=https://provider.example/send
SMS_HTTP_METHOD=POST
SMS_HTTP_HEADERS_JSON={"Authorization":"Bearer token","Content-Type":"application/json"}
SMS_HTTP_BODY_TEMPLATE={"to":"{{to}}","message":"{{message}}"}
```

Backend-ul inlocuieste doar `{{to}}` si `{{message}}`. Orice raspuns HTTP `2xx`
este tratat ca `sent`; restul devin `failed`, dar linkul ramane valid.

## Foldere rezultate

- snapshot-uri manuale: `./snapshots`
- inregistrari manuale: `./recordings`
- evenimente workflow: `./events`

## Oprire

Poti opri serverul cu `Ctrl+C` sau cu scriptul:

```bash
cd /Users/maleticimiroslav/CamereTedde/tedde/py_backend
./stop.sh
```

## Troubleshooting

### `/health` raspunde `degraded`

Serverul a pornit, dar una sau ambele camere nu raspund momentan.

### Snapshot / stream / record nu merg

Verifica:
- IP-urile camerelor
- user/parola in `.env`
- conectivitatea RTSP
- `FFMPEG_PATH`

### ALPR nu merge

Verifica:
- `ALPR_ENABLED=1`
- pachetul `fast-alpr` instalat
- camera configurata la `ALPR_CAMERA`
