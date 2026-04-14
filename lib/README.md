# Tedde `lib/` orchestrator

Bash entry point for operators. Target: macOS / Linux with `bash`, `curl`, and optional `lsof` (same as `py_backend/stop.sh`).

## Requirements

- Repo root `.env` (copy from `.env_example`) with camera IPs and RTSP credentials.
- Python venv at `.venv/` (recommended) or `python3` on `PATH` with dependencies from `py_backend/requirements.txt` (`pydantic`, `fastapi`, `fast-alpr`, `opencv-python-headless`, etc.).

## Commands

From repo root you can use either `./orchestrate.sh` (thin wrapper) or `./lib/orchestrate.sh` (same behavior).

| Command | Description |
|--------|-------------|
| `./orchestrate.sh start` | Start uvicorn in background; log file `logs/uvicorn.log`. |
| `./orchestrate.sh start foreground` | Run uvicorn in the foreground (blocks). |
| `./orchestrate.sh stop` | Stop listener on `PY_SERVER_PORT` (default 8000). |
| `./orchestrate.sh status` | Raw JSON: `curl` `/health` and `/api/health` with timeouts. |
| `./orchestrate.sh health` | Tabel colorat: `/api/health` + **ALPR live** (`POST /api/alpr/test`, camera `ALPR_CAMERA`) dacă serverul rulează; altfel probe locale (fără ALPR HTTP). Culori: verde OK, roșu FAIL (`NO_COLOR=1` le dezactivează). |
| `./orchestrate.sh sync-env` | Append to `.env` any keys present in `.env_example` but missing (keeps your secrets). Use `--dry-run` first. |
| `./orchestrate.sh first-configuration` | Health probes, optional server start, RTSP snapshot, ALPR detector benchmark, interactive `.env` update, then HTTP smoke tests. |
| `./orchestrate.sh test-record` | Triggers `POST /api/workflow/trigger`, polls until the workflow finishes, requires **at least one** valid MP4 under `EVENTS_DIR` (size ≥ 8 KB per file). Prints `WARNING` on stderr if only one camera succeeded. Optional: `python -m tools.workflow_wait … --strict-both` requires both cameras. Writes `logs/test_portal_last.json`. |
| `./orchestrate.sh test-send [EVENT_ID] [--no-sms]` | Calls `POST /api/customer-links` to create the customer portal URL (quiz → videos). Without `EVENT_ID`, uses `logs/test_portal_last.json` from `test-record`. Optional env: `TEST_PORTAL_OWNER_NAME`, `TEST_PORTAL_MECHANIC_NAME`, `TEST_PORTAL_PHONE`. |

## Test customer portal flow (`test-record` → `test-send`)

Prerequisites:

- Server running (`./orchestrate.sh start`). RTSP should work for each camera you expect; if one camera fails, the workflow can still finish with **one** valid MP4 — `test-record` and `POST /api/customer-links` succeed with warnings.
- `create_link` needs **at least one** usable `camera*.mp4` (same minimum size rule). The customer portal shows a prominent banner when only one video exists.
- `RECORDING_DURATION_SECONDS` in `.env` sets capture length; `test-record` waits up to that value **+ 90s** for ALPR, rename, and ffmpeg teardown.

Steps:

1. `./orchestrate.sh test-record` — writes `logs/test_portal_last.json` with `event_id`, `license_plate`, `base_url`.
2. `./orchestrate.sh test-send` — prints JSON plus `public_url`. With `SMS_BACKEND=mock`, SMS is logged instead of sent. Use `--no-sms` to set `send_sms: false` and only create the link.
3. Open `public_url` in a browser: quiz, then unlocked videos.

Troubleshooting:

- **HTTP 409** on trigger: another workflow or recording is already active; wait or `./orchestrate.sh stop` (if appropriate) and retry.
- **workflow_wait exit 5**: no valid MP4 under the event folder, or `--strict-both` while only one camera recorded (paths follow `EVENTS_DIR` in `.env`).
- **test-send HTTP 404**: wrong `event_id` or event folder removed from disk.

## Video, înregistrări și ALPR (clarificare)

```text
ESP / trigger
    └── WorkflowService
            ├── RecordingManager → events/<id>/camera1.mp4, camera2.mp4 (RTSP înregistrat)
            ├── save_snapshot → alpr_start.jpg
            └── ALPRService.predict_image (o singură imagine, nu tot MP4-ul)

Dashboard / API
    └── GET /api/events → linkuri la MP4 + metadata + alpr.json

Portal client (PUBLIC_BASE_URL + PORTAL_PATH_PREFIX)
    └── Pagină token → quiz → GET …/video/camera1|2 (MP4 din același eveniment)
```

- **Test ALPR live** din UI: `POST /api/alpr/test` — snapshot de la cameră, nu upload video.
- **ALPR pe video încărcat** (cadre eșantion + agregare): nu există încă în API; vezi design draft în [ALPR_VIDEO_RFC.md](ALPR_VIDEO_RFC.md).

## Security notes

- Scripts do not print `CAMERA_PASSWORD` or RTSP URLs with credentials.
- `curl` uses `--max-time` to avoid hanging.

## Python tools (called by shell)

- `python -m tools.health_standalone` — `startup_check.run_all()` without FastAPI.
- `python -m tools.health_pretty --standalone` — same probes, formatted table.
- `python -m tools.health_pretty --stdin` — format JSON piped from `curl …/api/health`.
- `python -m tools.health_pretty --full --base-url http://127.0.0.1:8000` — health + ALPR snapshot (folosit de `./orchestrate.sh health`).
- `python -m tools.sync_env_from_example` — merge missing keys from `.env_example` into `.env`.
- `python -m tools.first_config_alpr` — snapshot + benchmark + `.env` (requires `PYTHONPATH=py_backend` from repo root; the orchestrator sets this).
- `python -m tools.workflow_wait --base-url … --timeout … [--validate-under DIR] [--strict-both] [--write-state PATH]` — poll `/api/workflow/status` after a trigger (used by `test-record`). Default: ≥1 valid MP4; `--strict-both` requires both.
- `python -m tools.test_portal_send --base-url … --repo-root … [EVENT_ID] [--no-sms]` — `POST /api/customer-links` (used by `test-send`).

Run all commands from the **repository root** (directory containing `.env`).
