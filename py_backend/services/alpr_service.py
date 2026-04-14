"""
ALPR service wrapper around fast-alpr.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from config import settings

logger = logging.getLogger(__name__)

_AGENT_DEBUG_LOG = "/Users/maleticimiroslav/CamereTedde/tedde/.cursor/debug-e5dd89.log"


def _agent_debug_log(hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    # region agent log
    payload = {
        "sessionId": "e5dd89",
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        with open(_AGENT_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass
    # endregion


def normalize_plate_text(text: str) -> str:
    cleaned = re.sub(r"\s+", "", text.upper())
    cleaned = re.sub(r"[^A-Z0-9_-]", "", cleaned)
    return cleaned or "UNKNOWN"


def _predict_image_sync(model: Any, path_str: str) -> tuple[dict[str, Any], list[Any]]:
    """Load JPEG with OpenCV, run ALPR.predict(ndarray) (BGR as required by fast_alpr)."""
    import cv2

    meta: dict[str, Any] = {}
    img = cv2.imread(path_str)
    if img is None:
        meta["imread_ok"] = False
        return meta, []
    meta["imread_ok"] = True
    meta["shape_hwc"] = [int(x) for x in img.shape]
    results = model.predict(img)
    meta["alpr_n"] = len(results)
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
                logger.info(
                    "[ALPR] Loading fast-alpr (detector_conf_thresh=%s, detector_cpu_only=%s)...",
                    thresh,
                    cpu_only,
                )

                def _make_alpr() -> Any:
                    kw: dict[str, Any] = {"detector_conf_thresh": thresh}
                    if cpu_only:
                        kw["detector_providers"] = ["CPUExecutionProvider"]
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

        # region agent log
        try:
            st = image_path.stat()
            _agent_debug_log(
                "H4",
                "alpr_service.py:predict_image",
                "image_before_predict",
                {
                    "path": str(image_path),
                    "exists": image_path.is_file(),
                    "size_bytes": st.st_size,
                    "detector_conf_thresh": settings.alpr_detector_conf_thresh,
                    "detector_cpu_only": int(settings.alpr_detector_cpu_only),
                },
            )
        except OSError as e:
            _agent_debug_log(
                "H4",
                "alpr_service.py:predict_image",
                "image_stat_failed",
                {"path": str(image_path), "error": str(e)},
            )
        # endregion

        model = await self._get_model()
        sync_meta, results = await asyncio.to_thread(_predict_image_sync, model, str(image_path))
        # region agent log
        _agent_debug_log(
            "H8",
            "alpr_service.py:predict_image",
            "cv2_imread_and_predict",
            sync_meta,
        )
        if not sync_meta.get("imread_ok"):
            return {
                "enabled": True,
                "selected_plate": None,
                "selected_confidence": None,
                "plates": [],
                "load_error": "cv2 nu a putut citi imaginea (cale sau format invalid).",
            }
        # endregion

        plates: list[dict[str, Any]] = []

        # region agent log
        _agent_debug_log(
            "H1",
            "alpr_service.py:predict_image",
            "predict_raw_count",
            {"n_results": len(results)},
        )
        for idx, item in enumerate(results[:12]):
            det = getattr(item, "detection", None)
            ocr = getattr(item, "ocr", None)
            det_conf = float(det.confidence) if det is not None and hasattr(det, "confidence") else None
            det_label = getattr(det, "label", None) if det is not None else None
            ocr_text = (ocr.text or "")[:80] if ocr is not None else ""
            ocr_has = ocr is not None and bool(getattr(ocr, "text", None))
            _agent_debug_log(
                "H2" if not ocr_has else "H3",
                "alpr_service.py:predict_image",
                "result_item",
                {
                    "idx": idx,
                    "det_confidence": det_conf,
                    "det_label": det_label,
                    "ocr_present": ocr is not None,
                    "ocr_text_len": len(ocr_text) if ocr_text else 0,
                    "ocr_text_preview": ocr_text[:40] if ocr_text else None,
                    "skipped_no_ocr_text": not (ocr and getattr(ocr, "text", None)),
                },
            )
        # endregion

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
        # region agent log
        _agent_debug_log(
            "H5",
            "alpr_service.py:predict_image",
            "after_parse_plates",
            {
                "plates_kept": len(plates),
                "selected": selected["plate"] if selected else None,
            },
        )
        # endregion
        return {
            "enabled": True,
            "selected_plate": selected["plate"] if selected else None,
            "selected_confidence": selected["confidence"] if selected else None,
            "plates": plates,
        }
