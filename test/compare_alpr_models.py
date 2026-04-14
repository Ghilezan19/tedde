#!/usr/bin/env python3
"""
Compare fast-alpr plate detector ONNX variants on one image.

Run from repo root (downloads models on first use):

  .venv/bin/python test/compare_alpr_models.py snapshots/alpr_test_last.jpg
  .venv/bin/python test/compare_alpr_models.py path/to.jpg --cpu-only 0
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _ensure_test_path() -> None:
    test_dir = Path(__file__).resolve().parent
    if str(test_dir) not in sys.path:
        sys.path.insert(0, str(test_dir))


def main() -> int:
    _ensure_test_path()
    from alpr_benchmark_lib import ALL_PLATE_DETECTOR_MODELS, run_benchmark

    parser = argparse.ArgumentParser(description="Benchmark ALPR detector models on one JPEG/PNG.")
    parser.add_argument("image", type=Path, help="Path to image file")
    parser.add_argument(
        "--detectors",
        nargs="*",
        default=None,
        help="Detector model ids (default: all hub plate detectors)",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.1,
        help="detector_conf_thresh (default 0.1)",
    )
    parser.add_argument(
        "--ocr-model",
        default="cct-xs-v2-global-model",
        help="fast-plate-ocr hub model id",
    )
    parser.add_argument(
        "--cpu-only",
        type=int,
        default=1,
        choices=(0, 1),
        help="1 = CPUExecutionProvider for detector+OCR (default 1)",
    )
    args = parser.parse_args()
    path = args.image.resolve()
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    try:
        import cv2
    except ImportError as e:
        print(f"Import error: {e}", file=sys.stderr)
        print("Install: pip install opencv-python-headless", file=sys.stderr)
        return 1

    img = cv2.imread(str(path))
    if img is None:
        print(f"cv2.imread failed: {path}", file=sys.stderr)
        return 1

    detectors = list(args.detectors) if args.detectors else list(ALL_PLATE_DETECTOR_MODELS)
    cpu_only = bool(args.cpu_only)

    print(f"Image: {path}  shape={img.shape}  conf={args.conf}  ocr={args.ocr_model}\n")

    t_all = time.perf_counter()
    runs = run_benchmark(
        img,
        detector_models=detectors,
        ocr_model=args.ocr_model,
        conf_thresh=args.conf,
        cpu_only=cpu_only,
    )
    for row in runs:
        det = row["detector_model"]
        if row.get("error"):
            print(f"{det}: FAIL  {row['error']}\n")
            continue
        ms_i = row.get("ms_init")
        ms_p = row.get("ms_predict")
        nbox = row.get("n_boxes", 0)
        plates = row.get("plates") or []
        parts = []
        for p in plates:
            parts.append(f"{p['raw_plate']!r} ({p['confidence']}%)")
        line = " | ".join(parts) if parts else "(no OCR)"
        print(
            f"{det}\n"
            f"  init: {ms_i}ms  infer: {ms_p}ms  boxes: {nbox}  {line}\n"
        )
    print(f"Total wall time (sequential): {time.perf_counter() - t_all:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
