"""Bounded buffers and stream framing tests; no hardware FPS claims."""
import io
import unittest
from unittest.mock import patch

import test_api
from camera_bridge import LatestFrame, jpeg_frames
from app.services.camera_preview import PreviewStore, previews


class BufferTests(unittest.TestCase):
    def test_latest_slot_drops_backlog_and_rejects_stale_frames(self):
        latest = LatestFrame()
        with patch("camera_bridge.time.monotonic", return_value=0):
            for index in range(100):
                latest.put(str(index).encode())
            sequence, image = latest.get(timeout=0)
            self.assertEqual((sequence, image), (100, b"99"))
            self.assertIsNone(latest.get(after=100, timeout=0))
        with patch("camera_bridge.time.monotonic", return_value=3):
            self.assertIsNone(latest.get(timeout=0))

    def test_mjpeg_chunk_boundaries_and_multiple_frames(self):
        class Chunks:
            def __init__(self):
                self.chunks = iter([b"--boundary\r\nheaders\r\n\xff", b"\xd8abc\xff", b"\xd9\r\n--frame\r\n\xff\xd8next\xff\xd9", b""])
            def read(self, length):
                return next(self.chunks)
        frames = jpeg_frames(Chunks())
        self.assertEqual(next(frames), b"\xff\xd8abc\xff\xd9")
        self.assertEqual(next(frames), b"\xff\xd8next\xff\xd9")
        with self.assertRaises(OSError):
            next(frames)

    def test_ai_completion_never_rewinds_live_frame(self):
        store = PreviewStore()
        store.put("cam", b"video1")
        analysis = store.begin_analysis("cam", b"old-sampled-image", 7)
        store.put("cam", b"video2")
        store.update("cam", analysis, {"accepted": True})
        self.assertEqual(store.get("cam")["image"], b"video2")
        self.assertTrue(store.metadata("cam")["result"]["accepted"])
        self.assertEqual(store.metadata("cam")["session_id"], 7)


class CameraSocketTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    post = test_api.ApiTests.post
    frame = test_api.ApiTests.frame

    def test_binary_stream_uses_latest_after_ack(self):
        previews.frames.clear()
        previews.put("cam", b"first")
        token = self.auth["Authorization"].split(" ", 1)[1]
        with self.client.websocket_connect("/ws/devices/cam/camera") as socket:
            socket.send_json({"token": token})
            self.assertEqual(socket.receive_bytes(), b"first")
            previews.put("cam", b"discard-me")
            previews.put("cam", b"latest")
            socket.send_text("next")
            self.assertEqual(socket.receive_bytes(), b"latest")

    def test_camera_stream_rejects_invalid_token(self):
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/ws/devices/cam/camera") as socket:
                socket.send_json({"token": "wrong"})
                socket.receive_bytes()
