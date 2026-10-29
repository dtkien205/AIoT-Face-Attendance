"""Additional lifecycle, WebSocket, enrollment and late-arrival tests."""
import io
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

import cv2
import numpy as np

import test_api
from app.models import AttendanceSession
from app.models.school import utcnow
from app.services.images import validate_image
from app.services.antispoof import AntiSpoofAdapter
from evaluate_pad import summarize


class WorkflowTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    post = test_api.ApiTests.post
    frame = test_api.ApiTests.frame
    def test_websocket_receives_manual_and_close_events(self):
        token = self.auth["Authorization"].split(" ", 1)[1]
        with self.client.websocket_connect(f"/ws/sessions/{self.session_id}") as ws:
            ws.send_json({"token": token})
            self.assertEqual(ws.receive_json(), {"type": "ready"})
            self.post(f"/sessions/{self.session_id}/manual-attendance", {"student_id": self.student_id, "reason": "Verified card"})
            self.assertEqual(ws.receive_json()["type"], "liveness")
            self.assertEqual(ws.receive_json()["type"], "attendance")
            self.post(f"/sessions/{self.session_id}/close", {})
            self.assertEqual(ws.receive_json(), {"type": "session", "status": "closed"})

    def test_enrollment_and_revocation(self):
        _, image = cv2.imencode(".jpg", np.zeros((160, 160, 3), dtype=np.uint8))
        with patch("app.api.students.FaceRecognitionAdapter") as recognizer:
            recognizer.return_value.encode.return_value = np.zeros(128)
            response = self.client.post(f"/api/students/{self.student_id}/face", headers=self.auth,
                                       data={"consent": "true"}, files={"image": ("face.jpg", image.tobytes(), "image/jpeg")})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertFalse(response.json()["raw_image_stored"])
        self.assertTrue(self.client.get("/api/students", headers=self.auth).json()[0]["enrolled"])
        self.assertEqual(self.client.delete(f"/api/students/{self.student_id}/face", headers=self.auth).status_code, 204)
        self.assertFalse(self.client.get("/api/students", headers=self.auth).json()[0]["enrolled"])

    def test_late_arrival(self):
        with self.factory() as db:
            db.get(AttendanceSession, self.session_id).starts_at = utcnow() - timedelta(hours=1)
            db.commit()
        response = self.post(f"/sessions/{self.session_id}/manual-attendance", {"student_id": self.student_id, "reason": "Checked in late"})
        self.assertEqual(response.json()["attendance"]["status"], "late")

    def test_closed_frame_and_unsupported_media(self):
        response = self.client.post(f"/api/devices/cam/frames?session_id={self.session_id}", headers=self.device,
                                    files={"image": ("x.txt", b"x", "text/plain")})
        self.assertEqual(response.status_code, 415)
        self.post(f"/sessions/{self.session_id}/close", {})
        self.assertEqual(self.frame().status_code, 409)


class EvaluationTests(unittest.TestCase):
    def test_metrics(self):
        rows = [dict(label="live", real_score=.95, error=None, latency_ms=10),
                dict(label="live", real_score=.2, error=None, latency_ms=10),
                dict(label="print", real_score=.95, error=None, latency_ms=10),
                dict(label="replay", real_score=.2, error=None, latency_ms=10)]
        result = summarize(rows, .9)
        self.assertEqual(result["APCER"], .5)
        self.assertEqual(result["BPCER"], .5)

    def test_image_limits(self):
        from PIL import Image
        stream = io.BytesIO()
        Image.new("RGB", (2100, 2100)).save(stream, format="PNG")
        with self.assertRaises(ValueError):
            validate_image(stream.getvalue())
        with self.assertRaises(ValueError):
            validate_image(b"not an image")

    def test_pad_real_index_and_calibration(self):
        adapter = AntiSpoofAdapter.__new__(AntiSpoofAdapter)
        adapter.session = Mock()
        adapter.input_name, adapter.output_name, adapter.reason = "input", "output", "test"
        adapter.session.run.return_value = [np.array([[0., 10., 0.]])]
        with patch("app.services.antispoof.settings") as settings, patch("app.services.antispoof.prepare_face"):
            settings.pad_calibrated = True
            settings.pad_real_threshold = .9
            self.assertTrue(adapter.evaluate(b"x", (1, 1, 10, 10)).is_real)
            settings.pad_calibrated = False
            self.assertFalse(adapter.evaluate(b"x", (1, 1, 10, 10)).is_real)
            settings.pad_calibrated = True
            adapter.session.run.return_value = [np.array([[10., 0., 0.]])]
            self.assertFalse(adapter.evaluate(b"x", (1, 1, 10, 10)).is_real)
