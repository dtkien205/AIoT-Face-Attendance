"""Trial mode still requires PAD and identity; calibration flags are not falsified."""
import json
import unittest
from datetime import timedelta
from unittest.mock import patch

from app.models.school import CalibrationProfile, CameraTrial, Attendance, utcnow
from app.services.antispoof import PadResult
from app.services.face_detector import FaceDetection
from app.services.face_recognition import RecognitionResult
import test_api


class CameraTrialTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    post = test_api.ApiTests.post
    frame = test_api.ApiTests.frame

    def test_trial_auth_samples_confirmation_and_disable(self):
        self.assertEqual(self.client.post("/api/calibration/cam/trial", json={"confirmed": True}).status_code, 401)
        self.assertEqual(self.post("/calibration/cam/trial", {"confirmed": True}).status_code, 422)
        with self.factory() as db:
            db.add(CalibrationProfile(device_id="cam", samples=json.dumps([{"label": "live", "value": .99, "digest": str(i)} for i in range(3)])))
            db.commit()
        with patch("app.api.calibration._pad"), patch("app.api.calibration._recognizer"):
            self.assertEqual(self.post("/calibration/cam/trial", {"confirmed": False}).status_code, 422)
            result = self.post("/calibration/cam/trial", {"confirmed": True})
            self.assertEqual(result.status_code, 200, result.text)
        status = self.client.get("/api/system/status", headers=self.auth).json()
        self.assertIn("cam", status["trial_devices"])
        self.assertNotIn("cam", status["calibrated_devices"])
        self.assertEqual(self.client.delete("/api/calibration/cam/trial", headers=self.auth).status_code, 204)
        self.assertNotIn("cam", self.client.get("/api/system/status", headers=self.auth).json()["trial_devices"])

    def test_trial_pad_rejection_acceptance_label_and_expiry(self):
        with self.factory() as db:
            db.add(CameraTrial(device_id="cam", enabled_by="test", expires_at=utcnow() + timedelta(hours=2)))
            db.commit()
        detection = FaceDetection((40, 40, 80, 80), (80, 80), 6400, (160, 160), True, 1)
        with patch("app.api.attendance._detector") as detector, patch("app.api.attendance._pad") as pad, patch("app.api.attendance._recognizer") as recognizer:
            detector.return_value.detect_candidates.return_value = ([(detection, "ok")], "ok")
            pad.return_value.evaluate.return_value = PadResult(False, "spoof", .2)
            for _ in range(3): response = self.frame()
            self.assertFalse(response.json()["accepted"])
            recognizer.return_value.recognize.assert_not_called()
            pad.return_value.evaluate.return_value = PadResult(True, "passed", .99)
            recognizer.return_value.recognize.return_value = RecognitionResult("SV1", .1)
            response = self.frame()
            self.assertTrue(response.json()["accepted"])
            self.assertTrue(response.json()["trial"])
            self.assertEqual(pad.return_value.evaluate.call_args.kwargs, {"threshold": .9})
            self.assertEqual(recognizer.return_value.recognize.call_args.kwargs, {"threshold": .52})
            with self.factory() as db:
                from sqlalchemy import select
                self.assertTrue(db.scalar(select(Attendance)).verification.startswith("trial:"))
                db.get(CameraTrial, "cam").expires_at = utcnow() - timedelta(seconds=1)
                db.commit()
            self.frame()
            self.assertEqual(pad.return_value.evaluate.call_args.kwargs, {})
