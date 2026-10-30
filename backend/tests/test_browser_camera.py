"""Browser camera uses teacher auth and the existing fail-closed pipeline."""
import unittest
from unittest.mock import AsyncMock, patch

import test_api
from app.models import Attendance, Device
from sqlalchemy import select


class BrowserCameraTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    post = test_api.ApiTests.post

    def upload(self, headers=None):
        return self.client.post(f"/api/browser-camera/frames?session_id={self.session_id}",
                                headers=headers or {}, files={"image": ("x.jpg", b"bad", "image/jpeg")})

    def test_requires_teacher_auth(self):
        self.assertEqual(self.upload().status_code, 401)

    def test_uses_existing_pipeline_and_never_invents_acceptance(self):
        with patch("app.api.attendance._process_frame", new_callable=AsyncMock) as process:
            process.return_value = {"accepted": False, "reason": "PAD threshold needs calibration on this camera"}
            response = self.upload(self.auth)
            self.assertEqual(response.status_code, 202)
            self.assertFalse(response.json()["accepted"])
            self.assertTrue(process.call_args.args[0].startswith("browser-cam-"))
            with self.factory() as db:
                self.assertEqual(len(list(db.scalars(select(Attendance)))), 0)
                self.assertEqual(len(list(db.scalars(select(Device)))), 2)

    def test_closed_session_not_processed(self):
        self.post(f"/sessions/{self.session_id}/close", {})
        with patch("app.api.attendance._process_frame", new_callable=AsyncMock) as process:
            self.assertEqual(self.upload(self.auth).status_code, 409)
            process.assert_not_called()

    def test_invalid_image_rejected_without_attendance(self):
        response = self.upload(self.auth)
        self.assertEqual(response.status_code, 202)
        self.assertFalse(response.json()["accepted"])
        with self.factory() as db:
            self.assertEqual(len(list(db.scalars(select(Attendance)))), 0)
