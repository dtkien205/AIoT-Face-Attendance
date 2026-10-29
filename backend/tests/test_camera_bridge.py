"""SoftAP bridge tests without network or camera hardware."""
import unittest
from unittest.mock import Mock, patch

from camera_bridge import CameraBridge


class BridgeTests(unittest.TestCase):
    def bridge(self):
        return CameraBridge("http://192.168.4.1:81/capture", "http://localhost:8000", "cam", "test-token")

    def test_idle_probes_camera_before_heartbeat(self):
        bridge = self.bridge()
        bridge.capture = Mock(return_value=b"jpeg")
        bridge.api = Mock(side_effect=[{}, {"session_id": None, "active": False}, {"preview": True}])
        self.assertEqual(bridge.tick(0)["state"], "idle")
        bridge.capture.assert_called_once()
        self.assertEqual(bridge.api.call_count, 3)
        self.assertEqual(bridge.api.call_args_list[0].args[0], "/devices/heartbeat")

    def test_active_posts_binary_multipart_and_uses_backend_result(self):
        bridge = self.bridge()
        bridge.capture = Mock(return_value=b"\xff\xd8\x00\xff\xd9")
        bridge.api = Mock(side_effect=[{}, {"session_id": 7, "active": True}, {"accepted": False, "reason": "spoof"}])
        self.assertEqual(bridge.tick(0), {"state": "waiting", "reason": "spoof", "student_code": None, "created": None})
        upload = bridge.api.call_args
        self.assertEqual(upload.args[0], "/devices/cam/frames?session_id=7")
        self.assertIn(b'name="image"', upload.kwargs["body"])
        self.assertIn(b"\xff\xd8\x00\xff\xd9", upload.kwargs["body"])

    def test_camera_failure_never_updates_heartbeat(self):
        bridge = self.bridge()
        bridge.capture = Mock(side_effect=TimeoutError("offline"))
        bridge.api = Mock()
        with self.assertRaises(TimeoutError):
            bridge.tick(0)
        bridge.api.assert_not_called()

    def test_invalid_jpeg_and_urls(self):
        bridge = self.bridge()
        bridge.request = Mock(return_value=b"<html>error</html>")
        with self.assertRaises(ValueError):
            bridge.capture()
        with self.assertRaises(ValueError):
            CameraBridge("file:///etc/passwd", "http://localhost:8000", "cam", "token")
        with self.assertRaises(ValueError):
            CameraBridge("http://192.168.4.1:81/capture", "http://localhost:8000", "cam", "")

    def test_config_is_refreshed_without_restarting_bridge(self):
        bridge = self.bridge()
        bridge.capture = Mock(return_value=b"jpeg")
        bridge.api = Mock(side_effect=[{}, {"session_id": None, "active": False}, {"preview": True}, {"session_id": 4, "active": True}, {"accepted": True}])
        self.assertEqual(bridge.tick(0)["state"], "idle")
        self.assertEqual(bridge.tick(4)["state"], "accepted")
