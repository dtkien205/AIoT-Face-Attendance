"""Calibration uses real model scores in production; test scores are synthetic."""
import json
import unittest
from datetime import timedelta
from unittest.mock import patch

import cv2
import numpy as np
from sqlalchemy import select

import test_api
from app.api.calibration import report
from app.models.school import AttendanceSession, CalibrationProfile, SessionPause, utcnow
from app.services.antispoof import PadResult
from app.services.face_detector import FaceDetection
from app.services.face_recognition import RecognitionResult


class CalibrationResumeTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    post = test_api.ApiTests.post

    def test_resume_excludes_paused_time_and_preserves_start(self):
        now = utcnow()
        original = now - timedelta(minutes=65)
        with self.factory() as db:
            session = db.get(AttendanceSession, self.session_id)
            session.starts_at = original
            session.status = "closed"
            session.ends_at = now - timedelta(minutes=60)
            db.commit()
        result = self.post(f"/sessions/{self.session_id}/start", {})
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(result.json()["ends_at"])
        response = self.post(f"/sessions/{self.session_id}/manual-attendance", {"student_id": self.student_id, "reason": "Checked student card"})
        self.assertEqual(response.json()["attendance"]["status"], "present")
        # Calling start on an already-open session must not add another pause.
        self.post(f"/sessions/{self.session_id}/start", {})
        with self.factory() as db:
            session = db.get(AttendanceSession, self.session_id)
            self.assertEqual(session.starts_at.replace(tzinfo=None), original.replace(tzinfo=None))
            self.assertEqual(len(list(db.scalars(select(SessionPause)))), 1)
        self.post(f"/sessions/{self.session_id}/close", {})
        self.post(f"/sessions/{self.session_id}/start", {})
        duplicate = self.post(f"/sessions/{self.session_id}/manual-attendance", {"student_id": self.student_id, "reason": "Checked again"})
        self.assertFalse(duplicate.json()["created"])

    def test_resume_does_not_reset_time_already_elapsed(self):
        now = utcnow()
        with self.factory() as db:
            session = db.get(AttendanceSession, self.session_id)
            session.starts_at = now - timedelta(minutes=80)
            session.status = "closed"
            session.ends_at = now - timedelta(minutes=60)
            db.commit()
        self.post(f"/sessions/{self.session_id}/start", {})
        response = self.post(f"/sessions/{self.session_id}/manual-attendance", {"student_id": self.student_id, "reason": "Checked student card"})
        self.assertEqual(response.json()["attendance"]["status"], "late")

    def samples(self):
        return [{"label": label, "value": value, "digest": f"{label}-{index}"}
                for label, value in (("live", .98), ("replay", .3), ("same", .25), ("different", .7)) for index in range(3)]

    def test_apply_requires_auth_evidence_and_confirmation(self):
        payload = {"pad_threshold": .9, "recognition_threshold": .52, "confirmed": True}
        self.assertEqual(self.client.post("/api/calibration/cam/apply", json=payload).status_code, 401)
        self.assertEqual(self.post("/calibration/cam/apply", payload).status_code, 422)
        with self.factory() as db:
            db.add(CalibrationProfile(device_id="cam", samples=json.dumps(self.samples())))
            db.commit()
        self.assertEqual(self.post("/calibration/cam/apply", {**payload, "confirmed": False}).status_code, 422)
        self.assertEqual(self.post("/calibration/cam/apply", {**payload, "pad_threshold": .2}).status_code, 422)
        result = self.post("/calibration/cam/apply", payload)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["pad_threshold"], .9)
        self.assertIn("cam", self.client.get("/api/system/status", headers=self.auth).json()["calibrated_devices"])
        self.assertEqual(self.client.delete("/api/calibration/cam", headers=self.auth).status_code, 204)
        self.assertNotIn("cam", self.client.get("/api/system/status", headers=self.auth).json()["calibrated_devices"])

    def test_pipeline_uses_only_this_cameras_applied_thresholds(self):
        with self.factory() as db:
            db.add(CalibrationProfile(device_id="cam", samples=json.dumps(self.samples()), pad_threshold=.91,
                                      recognition_threshold=.45, applied_at=utcnow()))
            db.commit()
        detection = FaceDetection((40, 40, 80, 80), (80, 80), 6400, (160, 160), True, 1)
        with patch("app.api.attendance._detector") as detector, patch("app.api.attendance._pad") as pad, patch("app.api.attendance._recognizer") as recognizer:
            detector.return_value.detect_candidates.return_value = ([(detection, "ok")], "ok")
            pad.return_value.evaluate.return_value = PadResult(True, "passed", .99)
            recognizer.return_value.recognize.return_value = RecognitionResult("SV1", .1)
            for _ in range(3):
                response = test_api.ApiTests.frame(self)
            self.assertTrue(response.json()["accepted"])
            self.assertEqual(pad.return_value.evaluate.call_args.kwargs, {"threshold": .91})
            self.assertEqual(recognizer.return_value.recognize.call_args.kwargs, {"threshold": .45})

    def test_overlapping_samples_cannot_be_applied(self):
        samples = self.samples()
        samples.append({"label": "replay", "value": .999, "digest": "overlap"})
        self.assertFalse(report(CalibrationProfile(samples=json.dumps(samples)))["can_apply"])

    def test_sample_duplicate_and_new_sample_invalidates_approval(self):
        detection = FaceDetection((40, 40, 80, 80), (80, 80), 6400, (160, 160), True, 1)
        image = cv2.imencode(".jpg", np.zeros((160, 160, 3), dtype=np.uint8))[1].tobytes()
        with self.factory() as db:
            db.add(CalibrationProfile(device_id="cam", samples=json.dumps(self.samples()), pad_threshold=.9,
                                      recognition_threshold=.52, applied_at=utcnow()))
            db.commit()
        with patch("app.api.calibration._detector") as detector, patch("app.api.calibration._pad") as pad:
            detector.return_value.detect_largest.return_value = (detection, "ok")
            pad.return_value.evaluate.return_value = PadResult(False, "needs calibration", .99)
            def upload():
                return self.client.post("/api/calibration/cam/upload", headers=self.auth, data={"label": "live"}, files={"image": ("sample.jpg", image, "image/jpeg")})
            response = upload()
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIsNone(response.json()["applied_at"])
            self.assertEqual(upload().status_code, 409)
