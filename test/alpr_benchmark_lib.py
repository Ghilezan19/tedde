"""
Shared ALPR multi-detector benchmark helpers for local test tooling only.

Hub ids mirror py_backend.config.AlprPlateDetectorModel (keep in sync manually).
"""

from __future__ import annotations

import re
import time
from typing import Any

from fast_alpr import ALPR

# open_image_models plate detector hub names (same set as production config Literal).
ALL_PLATE_DETECTOR_MODELS: tuple[str, ...] = (
    "yolo-v9-s-608-license-plate-end2end",
    "yolo-v9-t-640-license-plate-end2end",
    "yolo-v9-t-512-license-plate-end2end",
    "yolo-v9-t-416-license-plate-end2end",
    "yolo-v9-t-384-license-plate-end2end",
    "yolo-v9-t-256-license-plate-end2end",
)


def normalize_plate_text(text: str) -> str:
    cleaned = re.sub(r"\s+", "", text.upper())
    cleaned = re.sub(r"[^A-Z0-9_-]", "", cleaned)
    return cleaned or "UNKNOWN"


def benchmark_one_detector(
    image_bgr: Any,
    detector_model: str,
    ocr_model: str,
    conf_thresh: float,
    cpu_only: bool,
) -> dict[str, Any]:
    """Build a fresh ALPR for one detector and run predict on an OpenCV BGR ndarray."""
    row: dict[str, Any] = {
        "detector_model": detector_model,
        "error": None,
        "plates": [],
        "selected_plate": None,
        "selected_confidence": None,
        "ms_init": None,
        "ms_predict": None,
        "n_boxes": 0,
    }
    try:
        kw: dict[str, Any] = {
            "detector_model": detector_model,
            "ocr_model": ocr_model,
            "detector_conf_thresh": conf_thresh,
        }
        if cpu_only:
            cpu = ["CPUExecutionProvider"]
            kw["detector_providers"] = cpu
            kw["ocr_providers"] = cpu
        t0 = time.perf_counter()
        alpr = ALPR(**kw)
        row["ms_init"] = int(round((time.perf_counter() - t0) * 1000))
        t1 = time.perf_counter()
        results = alpr.predict(image_bgr)
        row["ms_predict"] = int(round((time.perf_counter() - t1) * 1000))
        row["n_boxes"] = len(results)
        plates: list[dict[str, Any]] = []
        for item in results:
            if not item.ocr or not item.ocr.text:
                continue
            conf = item.ocr.confidence
            if isinstance(conf, list):
                conf_value = sum(conf) / len(conf) if conf else 0.0
            else:
                conf_value = float(conf or 0.0)
            plates.append(
                {
                    "plate": normalize_plate_text(item.ocr.text),
                    "raw_plate": item.ocr.text,
                    "confidence": round(conf_value * 100, 1),
                }
            )
        plates.sort(key=lambda p: p["confidence"], reverse=True)
        row["plates"] = plates
        if plates:
            row["selected_plate"] = plates[0]["plate"]
            row["selected_confidence"] = plates[0]["confidence"]
    except Exception as exc:
        row["error"] = str(exc)[:400]
    return row


def run_benchmark(
    image_bgr: Any,
    *,
    detector_models: list[str] | None = None,
    ocr_model: str = "cct-xs-v2-global-model",
    conf_thresh: float = 0.1,
    cpu_only: bool = True,
) -> list[dict[str, Any]]:
    models = detector_models if detector_models is not None else list(ALL_PLATE_DETECTOR_MODELS)
    return [
        benchmark_one_detector(image_bgr, name, ocr_model, conf_thresh, cpu_only)
        for name in models
    ]
