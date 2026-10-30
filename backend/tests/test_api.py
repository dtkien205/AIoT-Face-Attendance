"""Isolated API tests. AI acceptance is mocked; this is not PAD validation."""
import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

os.environ["ADMIN_PASSWORD"] = "test-password-only"
os.environ["DEVICE_TOKEN"] = "test-device-only"
os.environ["FRAME_INTERVAL_SECONDS"] = "0"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.database import Base, get_db
from app.main import create_app
from app.models import Attendance, Device
from app.models.school import utcnow, FaceReference
from app.services.antispoof import PadResult
from app.services.face_detector import FaceDetection
from app.services.face_recognition import RecognitionResult
from app.services.stability import gate


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.temp.name}/test.db", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)
        app = create_app()
        def db():
            with self.factory() as session:
                yield session
        app.dependency_overrides[get_db] = db
        self.client = TestClient(app)
        token = self.client.post("/api/auth/login", json={"username": "admin", "password": "test-password-only"}).json()["access_token"]
        self.auth = {"Authorization": f"Bearer {token}"}
        self.device = {"X-Device-Token": "test-device-only", "X-Device-ID": "cam"}
        self.class_id = self.post("/classes", {"code": "C1", "name": "Class"}).json()["id"]
        self.student_id = self.post("/students", {"student_code": "SV1", "name": "Student", "class_id": self.class_id}).json()["id"]
        self.session_id = self.post("/sessions", {"class_id": self.class_id, "title": "IoT"}).json()["id"]
        self.post(f"/sessions/{self.session_id}/start", {})
        self.client.post("/api/devices/heartbeat", json={"name": "Camera"}, headers=self.device)
        self.client.put("/api/devices/cam/config", headers=self.auth, json={"session_id": self.session_id})
        with self.factory() as db:
            db.add(FaceReference(student_id=self.student_id, embedding="[]", enrolled_by="test"))
            db.commit()
        gate.tracks.clear()

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def post(self, path, data):
        return self.client.post("/api" + path, headers=self.auth, json=data)

    def frame(self, body=None):
        if body is None:
            import cv2
            import numpy as np
            body = cv2.imencode(".jpg", np.zeros((160, 160, 3), dtype=np.uint8))[1].tobytes()
        return self.client.post(f"/api/devices/cam/frames?session_id={self.session_id}", headers=self.device,
                                files={"image": ("frame.jpg", body, "image/jpeg")})

    def test_teacher_and_device_auth(self):
        self.assertEqual(self.client.get("/api/students").status_code, 401)
        self.assertEqual(self.client.post("/api/devices/heartbeat", headers={"X-Device-ID": "cam"}, json={}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code, 401)

    def test_student_update_duplicate_and_foreign_key(self):
        self.assertEqual(self.post("/students", {"student_code": "sv1", "name": "duplicate"}).status_code, 409)
        self.assertEqual(self.post("/students", {"student_code": "X", "name": "X", "class_id": 999}).status_code, 404)
        self.assertEqual(self.client.put(f"/api/students/{self.student_id}", headers=self.auth,
                         json={"student_code": "SV1", "name": "Updated", "class_id": self.class_id}).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/classes/{self.class_id}", headers=self.auth).status_code, 409)

    def test_manual_attendance_duplicate_csv_and_close(self):
        payload = {"student_id": self.student_id, "reason": "Checked student card"}
        first = self.post(f"/sessions/{self.session_id}/manual-attendance", payload)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(first.json()["created"])
        self.assertFalse(self.post(f"/sessions/{self.session_id}/manual-attendance", payload).json()["created"])
        self.assertEqual(len(self.client.get("/api/attendance", headers=self.auth).json()), 1)
        report = self.client.get(f"/api/attendance/export?session_id={self.session_id}", headers=self.auth)
        self.assertIn("SV1", report.content.decode("utf-8-sig"))
        self.assertEqual(self.client.delete(f"/api/students/{self.student_id}", headers=self.auth).status_code, 409)
        self.post(f"/sessions/{self.session_id}/close", {})
        self.assertEqual(self.post(f"/sessions/{self.session_id}/manual-attendance", payload).status_code, 409)
        self.assertEqual(self.post(f"/sessions/{self.session_id}/start", {}).status_code, 200)
        self.assertFalse(self.post(f"/sessions/{self.session_id}/manual-attendance", payload).json()["created"])

    def test_attendance_analytics_filters_by_class_and_session(self):
        self.post(f"/sessions/{self.session_id}/manual-attendance",
                  {"student_id": self.student_id, "reason": "Checked student card"})
        other_class = self.post("/classes", {"code": "C2", "name": "Other class"}).json()["id"]
        self.post("/students", {"student_code": "SV2", "name": "Second", "class_id": other_class})
        other_session = self.post("/sessions", {"class_id": other_class, "title": "Other session"}).json()["id"]
        self.post(f"/sessions/{other_session}/start", {})

        all_data = self.client.get("/api/attendance/analytics", headers=self.auth).json()
        self.assertEqual(all_data["summary"]["sessions"], 2)
        self.assertEqual(all_data["summary"]["possible"], 2)
        class_data = self.client.get(f"/api/attendance/analytics?class_id={self.class_id}", headers=self.auth).json()
        self.assertEqual(class_data["summary"]["sessions"], 1)
        self.assertEqual(class_data["summary"]["attendance_rate"], 100.0)
        session_data = self.client.get(f"/api/attendance/analytics?session_id={other_session}", headers=self.auth).json()
        self.assertEqual(session_data["summary"]["sessions"], 1)
        self.assertEqual(session_data["summary"]["attended"], 0)
        self.assertEqual([item["student_code"] for item in session_data["low_attendance"]], ["SV2"])

    def test_other_class_cannot_attend(self):
        other = self.post("/students", {"student_code": "SV2", "name": "Other"}).json()["id"]
        self.assertEqual(self.post(f"/sessions/{self.session_id}/manual-attendance", {"student_id": other, "reason": "Test reason"}).status_code, 409)

    def test_bad_frame_and_no_attendance(self):
        response = self.frame()
        self.assertEqual(response.status_code, 202, response.text)
        self.assertFalse(response.json()["accepted"])
        self.assertEqual(self.client.get("/api/attendance", headers=self.auth).json(), [])
        self.assertTrue(self.client.get("/api/liveness-events", headers=self.auth).json())

    def test_pipeline_stability_pad_identity_and_duplicate(self):
        detection = FaceDetection((40, 40, 80, 80), (80, 80), 6400, (160, 160), True, 1)
        with patch("app.api.attendance._detector") as detector, patch("app.api.attendance._pad") as pad, patch("app.api.attendance._recognizer") as recognizer:
            detector.return_value.detect_candidates.return_value = ([(detection, "ok")], "ok")
            pad.return_value.evaluate.return_value = PadResult(True, "passed", .99)
            recognizer.return_value.recognize.return_value = RecognitionResult("SV1", .1)
            self.assertTrue(self.frame().json()["created"])
            self.assertFalse(self.frame().json()["created"])
            with self.factory() as db:
                self.assertEqual(len(list(db.scalars(select(Attendance)))), 1)

    def test_multiple_faces_prioritize_student_not_yet_attended(self):
        second_id = self.post("/students", {"student_code": "SV2", "name": "Second", "class_id": self.class_id}).json()["id"]
        self.post(f"/sessions/{self.session_id}/manual-attendance", {"student_id": self.student_id, "reason": "Already present"})
        with self.factory() as db:
            db.add(FaceReference(student_id=second_id, embedding="[]", enrolled_by="test"))
            db.commit()
        large = FaceDetection((20, 20, 100, 100), (70, 70), 10000, (160, 160), True, 1)
        small = FaceDetection((115, 40, 40, 40), (135, 60), 1600, (160, 160), True, 1)
        with patch("app.api.attendance._detector") as detector, patch("app.api.attendance._pad") as pad, patch("app.api.attendance._recognizer") as recognizer:
            detector.return_value.detect_candidates.return_value = ([(large, "ok"), (small, "ok")], "ok")
            pad.return_value.evaluate.return_value = PadResult(True, "passed", .99)
            recognizer.return_value.recognize.side_effect = [RecognitionResult("SV1", .1), RecognitionResult("SV2", .1)]
            result = self.frame().json()
        self.assertTrue(result["created"])
        self.assertEqual(result["student_code"], "SV2")

    def test_pad_rejection_and_error_fail_closed(self):
        detection = FaceDetection((40, 40, 80, 80), (80, 80), 6400, (160, 160), True, 1)
        with patch("app.api.attendance._detector") as detector, patch("app.api.attendance._pad") as pad:
            detector.return_value.detect_candidates.return_value = ([(detection, "ok")], "ok")
            pad.return_value.evaluate.return_value = PadResult(False, "spoof", .2)
            for _ in range(3): response = self.frame()
            self.assertFalse(response.json()["accepted"])
            pad.return_value.evaluate.side_effect = RuntimeError("model failed")
            self.assertFalse(self.frame().json()["accepted"])
            self.assertEqual(self.client.get("/api/attendance", headers=self.auth).json(), [])

    def test_roi_validation_and_offline(self):
        self.assertEqual(self.client.put("/api/devices/cam/config", headers=self.auth,
                         json={"roi_left": .9, "roi_right": .1}).status_code, 422)
        with self.factory() as db:
            db.get(Device, "cam").last_seen = utcnow() - timedelta(minutes=5)
            db.commit()
        self.assertEqual(self.client.get("/api/devices", headers=self.auth).json()[0]["status"], "offline")

    def test_enrollment_requires_consent(self):
        response = self.client.post(f"/api/students/{self.student_id}/face", headers=self.auth,
                                   data={"consent": "false"}, files={"image": ("face.jpg", b"bad", "image/jpeg")})
        self.assertEqual(response.status_code, 422)

    def test_websocket_without_auth_closes(self):
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(f"/ws/sessions/{self.session_id}") as ws:
                ws.send_json({"token": "invalid"})
                ws.receive_json()


if __name__ == "__main__":
    unittest.main()
