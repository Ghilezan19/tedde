# RFC: ALPR pe fișier video încărcat (neimplementat)

## Stare actuală (prod)

- ALPR rulează pe **JPEG** (`alpr_start.jpg` la workflow, `POST /api/alpr/test` pe snapshot RTSP).
- **MP4**-urile din evenimente sunt înregistrări RTSP (`camera1.mp4` / `camera2.mp4`), nu pipeline ALPR cadru-cadru.

## Obiectiv posibil

Permite încărcarea unui scurt MP4 (sau analiza unui fișier deja pe disc) și returnează plăcuțe detectate pe **N cadre** eșantionate (ex. ffmpeg `-vf fps=1/2` sau `-ss` echidistant).

## Cerințe de siguranță

- Limită mărime fișier (ex. 50 MB) și durată (ex. max 60 s de video procesat).
- Director temporar cu ștergere în `finally`.
- Fără logare URL/credențiale.
- Opțional: dezactivat implicit (`ALPR_VIDEO_UPLOAD_ENABLED=0`) sau doar CLI local (`tools/alpr_video_sample.py`), fără endpoint public.

## Pași tehnici (schiță)

1. `ffmpeg` extrage cadre PNG/JPEG într-un temp dir.
2. Pentru fiecare cadru (sau primul cu detecție): `ALPRService.predict_image` sau `fast_alpr` direct.
3. Agregare rezultate (unicat plăcuță, max confidence).
4. Timeout global (ex. 120 s).

## Alternative

- Doar **CLI** pentru operatori (același venv ca backend), fără HTTP.
- Dacă e nevoie de HTTP: `POST /api/internal/...` protejat (token local / localhost only).

Acest fișier este documentație de design; implementarea rămâne opțională.
