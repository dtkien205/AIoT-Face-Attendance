"""Bridge lifecycle tests never launch a camera process."""
import unittest
from unittest.mock import Mock, patch

from app.services.bridge_control import BridgeControl
import test_api


class BridgeControlTests(unittest.TestCase):
    def test_existing_preview_does_not_start_duplicate(self):
        control = BridgeControl()
        with patch("app.services.bridge_control.previews.get", return_value={"image": b"jpeg"}), patch("app.services.bridge_control.subprocess.Popen") as spawn:
            self.assertTrue(control.start()["connected"])
            spawn.assert_not_called()

    def test_unreachable_camera_does_not_launch_process(self):
        control = BridgeControl()
        with patch("app.services.bridge_control.previews.get", return_value=None), patch("app.services.bridge_control.socket.create_connection", side_effect=TimeoutError), patch("app.services.bridge_control.subprocess.Popen") as spawn:
            with self.assertRaises(OSError):
                control.start()
            spawn.assert_not_called()

    def test_managed_process_starts_once_and_stops(self):
        control = BridgeControl()
        process = Mock()
        process.poll.return_value = None
        with patch("app.services.bridge_control.previews.get", return_value=None), patch("app.services.bridge_control.socket.create_connection"), patch("app.services.bridge_control.subprocess.Popen", return_value=process) as spawn:
            self.assertTrue(control.start()["running"])
            self.assertTrue(control.start()["running"])
            spawn.assert_called_once()
            self.assertIsInstance(spawn.call_args.args[0], list)
            control.stop()
            process.terminate.assert_called_once()
            process.wait.assert_called_once_with(timeout=5)


class BridgeAuthTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    post = test_api.ApiTests.post

    def test_bridge_endpoints_require_teacher(self):
        with patch("app.api.devices.bridge") as bridge:
            self.assertEqual(self.client.get("/api/camera-bridge/status").status_code, 401)
            self.assertEqual(self.client.post("/api/camera-bridge/start").status_code, 401)
            self.assertEqual(self.client.post("/api/camera-bridge/stop").status_code, 401)
            bridge.start.assert_not_called()
            bridge.stop.assert_not_called()
            bridge.start.return_value = {"device_id": "cam", "running": True, "connected": False}
            response = self.client.post("/api/camera-bridge/start", headers=self.auth)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["running"])
