"""Optional dlib embeddings; stored references come only from consented enrollment."""
from __future__ import annotations

import io
import json
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select

from app.core.config import settings
from app.models.school import FaceReference, Student


@dataclass(frozen=True)
class RecognitionResult:
    student_code: str
    distance: float


class FaceRecognitionAdapter:
    def __init__(self):
        self.engine = None
        self.reason = "Install requirements-recognition.txt to enable face embeddings"
        try:
            import face_recognition
            self.engine = face_recognition
            self.reason = "ready" if settings.recognition_calibrated else "Recognition threshold needs calibration"
        except ImportError:
            pass

    @property
    def ready(self):
        return self.engine is not None and settings.recognition_calibrated

    def encode(self, image_bytes: bytes, box=None):
        if self.engine is None:
            raise ValueError(self.reason)
        image = self.engine.load_image_file(io.BytesIO(image_bytes))
        if box is None:
            locations = self.engine.face_locations(image)
            if len(locations) != 1:
                raise ValueError("Enrollment requires exactly one face")
        else:
            x, y, w, h = box
            locations = [(y, x + w, y + h, x)]
        encodings = self.engine.face_encodings(image, locations)
        if len(encodings) != 1 or not np.isfinite(encodings[0]).all():
            raise ValueError("Unable to encode face")
        return encodings[0]

    def recognize(self, image_bytes: bytes, box, db, class_id: int, *, threshold=None):
        if self.engine is None or (threshold is None and not self.ready):
            return None
        probe = self.encode(image_bytes, box)
        matches = []
        for reference, student in db.execute(
            select(FaceReference, Student).join(Student, Student.id == FaceReference.student_id)
            .where(Student.class_id == class_id)
        ):
            vector = np.asarray(json.loads(reference.embedding), dtype=np.float64)
            if vector.shape != (128,) or not np.isfinite(vector).all():
                continue
            matches.append((float(np.linalg.norm(vector - probe)), student.student_code))
        matches.sort()
        cutoff = settings.recognition_threshold if threshold is None else threshold
        if not 0 < cutoff <= 0.6 or not matches or matches[0][0] > cutoff:
            return None
        if len(matches) > 1 and matches[1][0] - matches[0][0] < settings.recognition_margin:
            return None
        return RecognitionResult(matches[0][1], matches[0][0])
