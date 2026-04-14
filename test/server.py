"""Local Flask endpoint for test/front.html — fast-alpr on port 5050."""

from __future__ import annotations

import os
import tempfile

import cv2
from flask import Flask, jsonify, request
from flask_cors import CORS
from fast_alpr import ALPR

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


if __name__ == "__main__":
    app.run(port=5050)
