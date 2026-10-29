"""Compatibility exports for older imports; use the focused service modules."""

from app.services.antispoof import AntiSpoofAdapter, PadResult
from app.services.face_recognition import FaceRecognitionAdapter, RecognitionResult

__all__ = ["AntiSpoofAdapter", "FaceRecognitionAdapter", "PadResult", "RecognitionResult"]
