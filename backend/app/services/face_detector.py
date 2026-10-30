"""OpenCV face detection and ROI/quality checks."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.core.config import settings
from app.core.domain import inside_roi


@dataclass(frozen=True)
class FaceDetection:
    box: tuple[int, int, int, int]
    center: tuple[float, float]
    area: int
    frame_size: tuple[int, int]
    roi_inside: bool
    quality_score: float


class FaceDetector:
    def __init__(self) -> None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self.cascade = cv2.CascadeClassifier(cascade_path)

    def detect_candidates(self, image_bytes: bytes, roi=(0.22, 0.15, 0.78, 0.85)) -> tuple[list[tuple[FaceDetection, str]], str]:
        if not image_bytes:
            return [], "empty image"
        frame = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return [], "invalid image"
        height, width = frame.shape[:2]

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(32, 32))
        if len(faces) == 0:
            return [], "no face detected"
        candidates = [face for face in faces if inside_roi(
            (face[0] + face[2] / 2, face[1] + face[3] / 2), (width, height), roi
        )]
        if not candidates:
            return [], "face outside ROI"
        results = []
        for x, y, box_width, box_height in sorted(candidates, key=lambda face: int(face[2]) * int(face[3]), reverse=True):
            center = (x + box_width / 2, y + box_height / 2)
            area = int(box_width * box_height)
            laplacian_variance = float(cv2.Laplacian(gray[y:y + box_height, x:x + box_width], cv2.CV_64F).var())
            detection = FaceDetection(
                box=(int(x), int(y), int(box_width), int(box_height)), center=center, area=area,
                frame_size=(width, height), roi_inside=inside_roi(center, (width, height), roi),
                quality_score=min(1.0, laplacian_variance / 500.0),
            )
            reason = "ok"
            if area / (width * height) < settings.min_face_area_ratio:
                reason = "face too small"
            elif laplacian_variance < settings.min_sharpness:
                reason = "image too blurry"
            results.append((detection, reason))
        return results, "ok"

    def detect_largest(self, image_bytes: bytes, roi=(0.22, 0.15, 0.78, 0.85)) -> tuple[FaceDetection | None, str]:
        candidates, reason = self.detect_candidates(image_bytes, roi)
        return candidates[0] if candidates else (None, reason)
