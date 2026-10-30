"""Manage one configured ESP32 relay without exposing its device token."""
import os
import socket
from urllib.parse import urlparse
from pathlib import Path
import subprocess
import sys
import threading

from app.core.config import settings
from app.services.camera_preview import previews


class BridgeControl:
    def __init__(self):
        self.process = None
        self.lock = threading.Lock()

    @property
    def device_id(self):
        return os.getenv("CAMERA_DEVICE_ID", "esp32-cam-01")

    def status(self):
        running = self.process is not None and self.process.poll() is None
        return {"device_id": self.device_id, "running": running,
                "connected": previews.get(self.device_id) is not None}

    def start(self):
        with self.lock:
            status = self.status()
            if status["connected"] or status["running"]:
                return status
            camera = urlparse(os.getenv("CAMERA_CAPTURE_URL", "http://192.168.4.1:81/capture"))
            if camera.scheme not in {"http", "https"} or not camera.hostname:
                raise OSError("Invalid configured camera URL")
            with socket.create_connection((camera.hostname, camera.port or (443 if camera.scheme == "https" else 80)), timeout=3):
                pass
            script = Path(__file__).resolve().parents[2] / "camera_bridge.py"
            env = dict(os.environ, DEVICE_TOKEN=settings.device_token)
            env["BRIDGE_BACKEND_URL"] = "http://127.0.0.1:8000"
            self.process = subprocess.Popen([sys.executable, str(script)], env=env,
                                            stdin=subprocess.DEVNULL)
            return self.status()

    def stop(self):
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            self.process = None
            return self.status()


bridge = BridgeControl()
