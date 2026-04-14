# Tedde Unified Camera Service

Serviciu Python-only bazat pe FastAPI pentru:
- dashboard web
- stream live MJPEG
- snapshot-uri si inregistrari
- control PTZ / audio / image settings
- workflow unic pentru browser + ESP
- ALPR integrat la startul workflow-ului

## Arhitectura

```text
Browser / ESP  <-->  FastAPI (Python)  <-->  ffmpeg  <-->  Camere RTSP
                        |
                        +-- /api/stream
                        +-- /api/snapshot
                        +-- /api/record/*
                        +-- /api/workflow/*
                        +-- /api/events
                        +-- /ws/audio
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
```

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
1. se pornesc inregistrarile pe camera 1 si 2
2. se face snapshot din camera configurata pentru ALPR
3. ruleaza ALPR
4. se creeaza folderul evenimentului
5. se salveaza `alpr_start.jpg`, `alpr.json`, `camera1.mp4`, `camera2.mp4`

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

