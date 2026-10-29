import unittest
from unittest.mock import patch

import cv2
import numpy as np

import test_api
from app.services.camera_preview import PreviewStore, previews


class PreviewApiTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    post = test_api.ApiTests.post
    frame = test_api.ApiTests.frame

    def test_authenticated_preview_without_attendance(self):
        previews.frames.clear()
        previews.results.clear()
        _, data = cv2.imencode(".jpg", np.zeros((160, 160, 3), dtype=np.uint8))
        response = self.client.post("/api/devices/cam/preview", headers=self.device,
                                    files={"image": ("frame.jpg", data.tobytes(), "image/jpeg")})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertFalse(response.json()["accepted"])
        self.assertEqual(self.client.get("/api/devices/cam/preview.jpg").status_code, 401)
        image = self.client.get("/api/devices/cam/preview.jpg", headers=self.auth)
        self.assertEqual(image.content, data.tobytes())
        self.assertEqual(image.headers["cache-control"], "no-store, private")
        metadata = self.client.get("/api/devices/cam/preview", headers=self.auth).json()
        self.assertTrue(metadata["available"])
        self.assertEqual(metadata["result"]["state"], "preview")
        self.assertNotIn("image", metadata)
        self.assertEqual(self.client.get("/api/attendance", headers=self.auth).json(), [])

    def test_missing_or_expired_preview(self):
        previews.frames.clear()
        previews.results.clear()
        self.assertFalse(self.client.get("/api/devices/cam/preview", headers=self.auth).json()["available"])
        self.assertEqual(self.client.get("/api/devices/cam/preview.jpg", headers=self.auth).status_code, 404)


class PreviewStoreTests(unittest.TestCase):
    def test_ttl_capacity_and_sequence(self):
        store = PreviewStore(ttl=10, capacity=2)
        with patch("app.services.camera_preview.time.monotonic", return_value=0):
            sequence = store.put("cam", b"first", 1)
            new_sequence = store.put("cam", b"new", 1)
            store.update("cam", sequence, {"accepted": True})
            self.assertNotIn("accepted", store.get("cam")["result"])
            store.update("cam", new_sequence, {"accepted": False})
            self.assertFalse(store.get("cam")["result"]["accepted"])
            store.put("cam2", b"second")
            store.put("cam3", b"third")
            self.assertIsNone(store.get("cam"))
        with patch("app.services.camera_preview.time.monotonic", return_value=11):
            self.assertIsNone(store.get("cam2"))
            self.assertEqual(len(store.frames), 0)
