"""MiniFASNetV2 ONNX adapter following yakhyo/face-anti-spoofing.

BGR float32 0..255, expanded crop 2.7, real class index 1. Never import
or execute the downloaded repository. Thresholds require local calibration.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.core.config import ROOT_DIR, settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PadResult:
    is_real: bool
    reason: str
    score: float | None = None


def prepare_face(image_bytes: bytes, box: tuple[int, int, int, int], size=(80, 80), scale=2.7):
    frame = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("invalid image")
    height, width = frame.shape[:2]
    x, y, w, h = box
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width or y + h > height:
        raise ValueError("invalid face box")
    scale = min((height - 1) / h, (width - 1) / w, scale)
    cx, cy = x + w / 2, y + h / 2
    left, top = max(0, int(cx - w * scale / 2)), max(0, int(cy - h * scale / 2))
    right, bottom = min(width - 1, int(cx + w * scale / 2)), min(height - 1, int(cy + h * scale / 2))
    crop = cv2.resize(frame[top:bottom + 1, left:right + 1], size[::-1])
    return np.ascontiguousarray(crop.transpose(2, 0, 1)[None], dtype=np.float32)


class AntiSpoofAdapter:
    def __init__(self):
        self.session = None
        self.reason = "PAD model is not configured"
        self.model = "MiniFASNetV2 ONNX"
        path = Path(settings.pad_model_path) if settings.pad_model_path else None
        if path is None:
            return
        if not path.is_absolute():
            path = ROOT_DIR / path
        if not path.is_file():
            self.reason = "PAD model file is missing"
            return
        try:
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
            input_info = session.get_inputs()[0]
            if input_info.type != "tensor(float)" or input_info.shape[1:] != [3, 80, 80]:
                raise ValueError("Expected MiniFASNet input N×3×80×80 float32")
            self.input_name = input_info.name
            self.output_name = session.get_outputs()[0].name
            self.session = session
            self.reason = "ready" if settings.pad_calibrated else "PAD threshold needs calibration on this camera"
        except Exception:
            logger.exception("PAD model load failed")
            self.reason = "PAD model or ONNX runtime incompatible; see server log"

    @property
    def ready(self):
        return self.session is not None and settings.pad_calibrated and 0.5 < settings.pad_real_threshold < 1

    def evaluate(self, image_bytes: bytes, box=None) -> PadResult:
        if not image_bytes or box is None:
            return PadResult(False, "valid detected face is required")
        if self.session is None:
            return PadResult(False, self.reason)
        try:
            tensor = prepare_face(image_bytes, box, scale=settings.pad_crop_scale)
            logits = np.asarray(self.session.run([self.output_name], {self.input_name: tensor})[0])
            if logits.shape != (1, 3) or not np.isfinite(logits).all():
                return PadResult(False, "invalid PAD output")
            probs = np.exp(logits - logits.max(axis=1, keepdims=True))
            probs /= probs.sum(axis=1, keepdims=True)
            score = float(probs[0, 1])
            if not self.ready:
                return PadResult(False, self.reason, score)
            passed = int(np.argmax(probs[0])) == 1 and score >= settings.pad_real_threshold
            return PadResult(passed, "PAD passed" if passed else "spoof or uncertain PAD score", score)
        except Exception:
            logger.exception("PAD inference failed")
            return PadResult(False, "PAD inference error")
