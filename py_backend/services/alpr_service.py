"""
ALPR service wrapper around fast-alpr.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from config import settings

logger = logging.getLogger(__name__)


def normalize_plate_text(text: str) -> str:
    cleaned = re.sub(r"\s+", "", text.upper())
    cleaned = re.sub(r"[^A-Z0-9_-]", "", cleaned)
    return cleaned or "UNKNOWN"


def _predict_image_sync(model: Any, path_str: str) -> tuple[dict[str, Any], list[Any]]:
    """Load JPEG with OpenCV, run ALPR.predict(ndarray) (BGR). Optional upscale retry if no boxes."""
    import cv2

    meta: dict[str, Any] = {}
    img = cv2.imread(path_str)
    if img is None:
        meta["imread_ok"] = False
        return meta, []
    meta["imread_ok"] = True
    meta["shape_hwc"] = [int(x) for x in img.shape]

    def _run(im: Any) -> list[Any]:
        try:
            return model.predict(im)
        except Exception as exc:
            errs = meta.setdefault("predict_errors", [])
            errs.append(type(exc).__name__ + ":" + str(exc)[:120])
            return []

    results = _run(img)
    meta["alpr_n"] = len(results)
    if results:
        meta["first_det_conf"] = round(float(results[0].detection.confidence), 4)
        return meta, results

    # Letterbox la 384px micșorează plăcuțe mici / off-domain (ex. pe tablă) — retry pe cadru mărit.
    if (
        int(settings.alpr_upscale_retry) == 1
        and min(img.shape[0], img.shape[1]) >= 400
    ):
        usf = float(settings.alpr_predict_upscale)
        h2 = int(round(img.shape[0] * usf))
        w2 = int(round(img.shape[1] * usf))
        up = cv2.resize(img, (w2, h2), interpolation=cv2.INTER_CUBIC)
        meta["upscale_factor"] = usf
        meta["upscale_shape_hwc"] = [h2, w2, 3]
        results = _run(up)
        meta["alpr_n_after_upscale"] = len(results)
        if results:
            meta["first_det_conf"] = round(float(results[0].detection.confidence), 4)

    return meta, results


class ALPRService:
    def __init__(self) -> None:
        self._alpr = None
        self._lock = asyncio.Lock()

    async def _get_model(self):
        if self._alpr is not None:
            return self._alpr
        async with self._lock:
            if self._alpr is None:
                from fast_alpr import ALPR

                thresh = float(settings.alpr_detector_conf_thresh)
                cpu_only = int(settings.alpr_detector_cpu_only) == 1
                det_model = settings.alpr_detector_model
                ocr_model = settings.alpr_ocr_model
                logger.info(
                    "[ALPR] Loading fast-alpr detector=%s ocr=%s thresh=%s cpu_only=%s",
                    det_model,
                    ocr_model,
                    thresh,
                    cpu_only,
                )

                def _make_alpr() -> Any:
                    kw: dict[str, Any] = {
                        "detector_model": det_model,
                        "ocr_model": ocr_model,
                        "detector_conf_thresh": thresh,
                    }
                    if cpu_only:
                        # OCR pe același provider evită cazuri CoreML ciudate după detecție.
                        cpu = ["CPUExecutionProvider"]
                        kw["detector_providers"] = cpu
                        kw["ocr_providers"] = cpu
                    return ALPR(**kw)

                self._alpr = await asyncio.to_thread(_make_alpr)
                logger.info("[ALPR] Model ready")
        return self._alpr

    async def predict_image(self, image_path: Path) -> dict[str, Any]:
        if not settings.alpr_enabled:
            return {
                "enabled": False,
                "selected_plate": None,
                "selected_confidence": None,
                "plates": [],
            }

        model = await self._get_model()
        sync_meta, results = await asyncio.to_thread(_predict_image_sync, model, str(image_path))
        if not sync_meta.get("imread_ok"):
            return {
                "enabled": True,
                "selected_plate": None,
                "selected_confidence": None,
                "plates": [],
                "load_error": "cv2 nu a putut citi imaginea (cale sau format invalid).",
            }

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

        plates.sort(key=lambda plate: plate["confidence"], reverse=True)
        selected = plates[0] if plates else None
        return {
            "enabled": True,
            "selected_plate": selected["plate"] if selected else None,
            "selected_confidence": selected["confidence"] if selected else None,
            "plates": plates,
        }
