"""Local Flask endpoint for test/front.html — fast-alpr on port 5050."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import cv2
from flask import Flask, jsonify, request
from flask_cors import CORS
from fast_alpr import ALPR

_TEST_DIR = Path(__file__).resolve().parent
if str(_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_TEST_DIR))

from alpr_benchmark_lib import run_benchmark  # noqa: E402

app = Flask(__name__)
CORS(app)
alpr = ALPR()


@app.route("/recognize", methods=["POST"])
def recognize():
    f = request.files["image"]
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        f.save(tmp.name)
        path = tmp.name
    try:
        img = cv2.imread(path)
        if img is None:
            return jsonify({"error": "invalid image", "plates": []}), 400
        results = alpr.predict(img)
    finally:
        if os.path.exists(path):
            os.unlink(path)

    plates = []
    for r in results:
        if r.ocr and r.ocr.text:
            conf = r.ocr.confidence
            if isinstance(conf, list):
                conf = sum(conf) / len(conf) if conf else 0.0
            plates.append(
                {"plate": r.ocr.text, "confidence": round(float(conf) * 100, 1)}
            )
    return jsonify({"plates": plates})


@app.route("/benchmark", methods=["POST"])
def benchmark():
    if "image" not in request.files:
        return jsonify({"error": "missing file field image", "runs": []}), 400
    f = request.files["image"]
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        f.save(tmp.name)
        path = tmp.name
    try:
        img = cv2.imread(path)
        if img is None:
            return jsonify({"error": "invalid image", "runs": []}), 400
        ocr_model = request.form.get("ocr_model") or "cct-xs-v2-global-model"
        try:
            conf = float(request.form.get("conf", "0.1"))
        except ValueError:
            conf = 0.1
        raw_cpu = (request.form.get("cpu_only", "1") or "1").strip()
        cpu_only = raw_cpu not in ("0", "false", "False")
        runs = run_benchmark(img, ocr_model=ocr_model, conf_thresh=conf, cpu_only=cpu_only)
        return jsonify(
            {
                "runs": runs,
                "ocr_model": ocr_model,
                "detector_conf_thresh": conf,
                "detector_cpu_only": cpu_only,
            }
        )
    finally:
        if os.path.exists(path):
            os.unlink(path)


if __name__ == "__main__":
    app.run(port=5050)
