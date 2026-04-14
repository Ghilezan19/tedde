"""
First-time ALPR detector selection: snapshot (optional), benchmark all detectors, update .env.

Run from repo root:
  PYTHONPATH=py_backend python -m tools.first_config_alpr --camera 1 --quality main
  PYTHONPATH=py_backend python -m tools.first_config_alpr --image snapshots/foo.jpg
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = REPO_ROOT / ".env"


def _backup_env(env_path: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak = env_path.with_suffix(env_path.suffix + f".bak.{ts}")
    shutil.copy2(env_path, bak)
    return bak


def update_env_key(env_path: Path, key: str, value: str) -> None:
    if "\n" in value or "\r" in value:
        raise ValueError("Invalid env value")
    text = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
    lines = text.splitlines(keepends=True)
    if not lines and text:
        lines = [text]
    prefix = f"{key}="
    new_lines: list[str] = []
    found = False
    for line in lines:
        stripped = line.lstrip().replace("\r", "")
        if stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        k = stripped.split("=", 1)[0].strip()
        if k == key:
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        new_lines.append(f"{key}={value}\n")
    tmp = env_path.with_suffix(".tmp")
    tmp.write_text("".join(new_lines), encoding="utf-8")
    tmp.replace(env_path)


def _print_runs_table(runs: list[dict]) -> None:
    print("\n--- Rezultate benchmark detectoare ---")
    print(f"{'Detector':<42} {'Plăcuță':<14} {'Cutii':>5} {'Init':>6} {'Pred':>6}  Eroare")
    for r in runs:
        plate = r.get("selected_plate") or "—"
        conf = r.get("selected_confidence")
        if conf is not None and plate != "—":
            plate = f"{plate} ({conf}%)"
        err = (r.get("error") or "")[:50]
        print(
            f"{r['detector_model']:<42} {plate:<14} {r.get('n_boxes', 0)!s:>5} "
            f"{r.get('ms_init')!s:>6} {r.get('ms_predict')!s:>6}  {err}"
        )


def _pick_interactive(runs: list[dict]) -> str | None:
    candidates = [
        r
        for r in runs
        if r.get("selected_plate") and not r.get("error")
    ]
    candidates.sort(
        key=lambda r: (
            -(r.get("selected_confidence") or 0.0),
            -(r.get("n_boxes") or 0),
        )
    )
    _print_runs_table(runs)

    if not candidates:
        print("\nNiciun detector nu a produs text OCR valid. Ajustează cadru/prag sau încearcă alt stream.")
        return None

    if len(candidates) == 1:
        c = candidates[0]
        ans = input(
            f"\nUn singur candidat: {c['detector_model']} → {c['selected_plate']}. "
            f"Enter confirmă, sau n pentru renunțare: "
        ).strip()
        if ans.lower() in ("n", "no", "nu"):
            return None
        return str(c["detector_model"])

    print("\nDetectoare cu plăcuță citită (sortate după încredere):")
    for i, c in enumerate(candidates, 1):
        print(
            f"  {i}) {c['detector_model']}\n"
            f"      plăcuță: {c['selected_plate']}  ({c.get('selected_confidence')}%)"
        )
    print("  m) introdu manual id hub complet al detectorului")
    choice = input("\nAlege număr (implicit 1): ").strip() or "1"
    if choice.lower() == "m":
        manual = input("ID detector (ex. yolo-v9-t-512-license-plate-end2end): ").strip()
        return manual or None
    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(candidates):
            return str(candidates[idx - 1]["detector_model"])
    print("Selecție invalidă.", file=sys.stderr)
    return None


async def _snapshot(camera: int, quality: str, out: Path) -> None:
    from camera.media import save_snapshot

    await save_snapshot(camera=camera, quality=quality, filepath=out)


def main() -> None:
    parser = argparse.ArgumentParser(description="First-config: snapshot + ALPR detector benchmark + .env")
    parser.add_argument("--camera", type=int, choices=(1, 2), help="Capture RTSP snapshot from this camera")
    parser.add_argument("--quality", choices=("main", "sub"), default="main")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="JPEG path for snapshot (implicit: snapshots/first_config_last.jpg sub settings)",
    )
    parser.add_argument("--image", type=Path, default=None, help="Use existing image instead of snapshot")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--skip-write", action="store_true", help="Do not modify .env")
    args = parser.parse_args()

    from config import settings
    from tools.alpr_detector_benchmark import run_benchmark

    img_path: Path
    if args.image is not None:
        img_path = args.image.resolve()
        if not img_path.is_file():
            print(f"Lipsește fișierul: {img_path}", file=sys.stderr)
            sys.exit(1)
    elif args.camera is not None:
        out = args.output or (settings.snapshot_dir_abs / "first_config_last.jpg")
        out = Path(out)
        print(f"Capture snapshot cameră {args.camera} ({args.quality}) → {out} …")
        try:
            asyncio.run(_snapshot(args.camera, args.quality, out))
        except Exception as exc:
            print(f"Snapshot eșuat: {exc}", file=sys.stderr)
            sys.exit(1)
        img_path = out
    else:
        parser.error("Specifică --camera sau --image")

    try:
        import cv2
    except ImportError:
        print("Instalează opencv-python-headless.", file=sys.stderr)
        sys.exit(1)

    bgr = cv2.imread(str(img_path))
    if bgr is None:
        print(f"cv2.imread a eșuat: {img_path}", file=sys.stderr)
        sys.exit(1)

    ocr_model = str(settings.alpr_ocr_model)
    conf = float(settings.alpr_detector_conf_thresh)
    cpu_only = int(settings.alpr_detector_cpu_only) == 1

    print(
        f"\nBenchmark pe {img_path}  OCR={ocr_model}  conf={conf}  CPU-only={cpu_only} "
        f"(durează la prima rulare — descărcare modele)…\n"
    )
    runs = run_benchmark(bgr, ocr_model=ocr_model, conf_thresh=conf, cpu_only=cpu_only)

    chosen = _pick_interactive(runs)
    if chosen is None:
        sys.exit(2)

    if args.skip_write:
        print(f"Skip write: detector ales ar fi fost: {chosen}")
        sys.exit(0)

    env_path = args.env_file.resolve()
    if not env_path.is_file():
        print(f"Lipsește {env_path}", file=sys.stderr)
        sys.exit(1)

    bak = _backup_env(env_path)
    print(f"\nBackup .env: {bak}")
    update_env_key(env_path, "ALPR_DETECTOR_MODEL", chosen)
    print(f"Scriere ALPR_DETECTOR_MODEL={chosen} în {env_path}")
    print("Repornește serverul FastAPI ca să încarce noul model.")


if __name__ == "__main__":
    main()
