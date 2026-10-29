"""Low-latency SoftAP camera relay: independent MJPEG preview and sampled AI.

Runs on Windows/Linux with Python standard library only, or via Compose profile
camera-ap. No AI runs here; accepted=true must come from the backend.
"""
from __future__ import annotations

import argparse
import http.client
import threading
import json
import logging
import os
import secrets
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import ProxyHandler, Request, build_opener

LOG = logging.getLogger("camera-bridge")
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def load_env(path: Path):
    """Read simple KEY=value dotenv entries without executing shell code."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep and key.strip().replace("_", "").isalnum():
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)


class LatestFrame:
    """One slot shared by independent readers: bounded memory, never a queue."""
    def __init__(self):
        self.condition = threading.Condition()
        self.sequence = 0
        self.value = None
        self.received = 0

    def put(self, image):
        with self.condition:
            self.sequence += 1
            self.value, self.received = image, time.monotonic()
            self.condition.notify_all()

    def get(self, after=0, timeout=1, max_age=2):
        with self.condition:
            self.condition.wait_for(lambda: self.sequence > after, timeout=timeout)
            if self.sequence <= after or time.monotonic() - self.received > max_age:
                return None
            return self.sequence, self.value


def jpeg_frames(response):
    """Bounded JPEG extraction, compatible with old ESP32's MJPEG boundary order."""
    buffer = bytearray()
    read = getattr(response, "read1", response.read)
    while True:
        chunk = read(16384)
        if not chunk:
            raise OSError("Camera stream ended")
        buffer.extend(chunk)
        while True:
            start = buffer.find(b"\xff\xd8")
            if start < 0:
                if len(buffer) > 65536:
                    del buffer[:-1]
                break
            if start:
                del buffer[:start]
            end = buffer.find(b"\xff\xd9", 2)
            if end < 0:
                if len(buffer) > MAX_IMAGE_BYTES:
                    raise ValueError("Camera frame exceeds size limit")
                break
            if end + 2 > MAX_IMAGE_BYTES:
                raise ValueError("Camera frame exceeds size limit")
            yield bytes(buffer[:end + 2])
            del buffer[:end + 2]


class BackendConnection:
    """One persistent HTTP connection per worker; safe to reconnect after errors."""
    def __init__(self, base_url, token, device_id, timeout):
        self.url = urlparse(base_url)
        self.headers = {"X-Device-ID": device_id, "X-Device-Token": token}
        self.timeout, self.connection = timeout, None

    def close(self):
        if self.connection:
            self.connection.close()
        self.connection = None

    def request(self, path, body=None, content_type=None):
        if self.connection is None:
            cls = http.client.HTTPSConnection if self.url.scheme == "https" else http.client.HTTPConnection
            self.connection = cls(self.url.hostname, self.url.port, timeout=self.timeout)
        headers = dict(self.headers)
        if content_type:
            headers["Content-Type"] = content_type
        try:
            self.connection.request("POST" if body is not None else "GET", self.url.path.rstrip("/") + "/api" + path, body, headers)
            response = self.connection.getresponse()
            data = response.read(65537)
            if len(data) > 65536:
                raise ValueError("Backend response too large")
            if response.status >= 400:
                raise ValueError(f"Backend HTTP {response.status}: check token/session/rate")
            return json.loads(data)
        except Exception:
            self.close()
            raise

    def json(self, path, payload):
        return self.request(path, json.dumps(payload).encode(), "application/json")

    def image(self, path, image):
        boundary = "BTLFrame" + secrets.token_hex(8)
        head = f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="frame.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
        return self.request(path, head + image + f"\r\n--{boundary}--\r\n".encode(),
                            f"multipart/form-data; boundary={boundary}")


class CameraBridge:
    def __init__(self, camera_url, backend_url, device_id, token, interval=.8, timeout=5):
        for value in (camera_url, backend_url):
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("URLs must be HTTP(S), without embedded credentials")
        if not device_id or len(device_id) > 64 or not token:
            raise ValueError("DEVICE_ID (1–64 characters) and DEVICE_TOKEN are required")
        if interval < .4 or timeout <= 0:
            raise ValueError("Interval must be at least 0.4 seconds; timeout must be positive")
        self.camera_url = camera_url
        self.backend_url = backend_url.rstrip("/")
        self.device_id, self.token = device_id, token
        self.interval, self.timeout = interval, timeout
        # Local camera/backend traffic must not use system HTTP proxies.
        self.opener = build_opener(ProxyHandler({}))
        self.next_heartbeat = 0
        self.next_config = 0
        self.config = {"active": False, "session_id": None}

    def request(self, url, *, body=None, headers=None, limit=65536):
        request = Request(url, data=body, headers=headers or {})
        with self.opener.open(request, timeout=self.timeout) as response:
            data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError("Response exceeds size limit")
            return data

    def api(self, path, payload=None, *, body=None, content_type=None):
        if payload is not None:
            body = json.dumps(payload).encode()
            content_type = "application/json"
        headers = {"X-Device-ID": self.device_id, "X-Device-Token": self.token}
        if content_type:
            headers["Content-Type"] = content_type
        return json.loads(self.request(self.backend_url + "/api" + path, body=body, headers=headers))

    def capture(self):
        data = self.request(self.camera_url, limit=MAX_IMAGE_BYTES)
        if not data.startswith(b"\xff\xd8"):
            raise ValueError("Camera /capture did not return a JPEG image")
        return data

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        # Heartbeat means the camera really responded, not merely bridge alive.
        image = self.capture()
        if now >= self.next_heartbeat:
            self.api("/devices/heartbeat", {"name": "ESP32-CAM · SoftAP bridge", "ip_address": urlparse(self.camera_url).hostname})
            self.next_heartbeat = now + 10
        if now >= self.next_config:
            config = self.api("/devices/config")
            if not isinstance(config, dict):
                raise ValueError("Invalid backend config response")
            self.config = config
            self.next_config = now + 3
        session_id = self.config.get("session_id")
        active = self.config.get("active") and isinstance(session_id, int) and session_id > 0
        boundary = "BTLFrame" + secrets.token_hex(12)
        head = f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="frame.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
        body = head + image + f"\r\n--{boundary}--\r\n".encode()
        path = f"/devices/{quote(self.device_id, safe='')}/frames?session_id={session_id}" if active else f"/devices/{quote(self.device_id, safe='')}/preview"
        result = self.api(path,
                          body=body, content_type=f"multipart/form-data; boundary={boundary}")
        if not active:
            return {"state": "idle", "reason": "Camera preview connected; assign an open session in dashboard"}
        if not isinstance(result, dict) or not isinstance(result.get("accepted"), bool):
            raise ValueError("Invalid attendance response")
        return {"state": "accepted" if result["accepted"] else "waiting",
                "reason": result.get("reason", "Backend confirmed attendance"),
                "student_code": result.get("student_code"), "created": result.get("created")}

    def run(self):
        latest = LatestFrame()
        stop = threading.Event()
        stream_url = os.getenv("CAMERA_STREAM_URL", self.camera_url.rsplit("/", 1)[0] + "/stream")
        parsed = urlparse(stream_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("CAMERA_STREAM_URL must be an HTTP(S) URL without credentials")
        mode = os.getenv("CAMERA_TRANSPORT", "mjpeg")
        if mode not in {"mjpeg", "snapshot"}:
            raise ValueError("CAMERA_TRANSPORT must be mjpeg or snapshot")
        fps = max(1, min(30, float(os.getenv("CAMERA_PREVIEW_FPS", "15"))))
        prefix = "/devices/" + quote(self.device_id, safe="")

        def reader():
            while not stop.is_set():
                try:
                    if mode == "snapshot":
                        latest.put(self.capture())
                        stop.wait(1 / fps)
                    else:
                        # Only ONE connection to the old single-thread camera server.
                        # Never request /capture while holding /stream open.
                        with self.opener.open(stream_url, timeout=self.timeout) as response:
                            for image in jpeg_frames(response):
                                latest.put(image)
                                if stop.is_set():
                                    return
                except (OSError, ValueError, http.client.HTTPException) as exc:
                    LOG.warning("Camera read failed (%s): %s", mode, exc)
                    stop.wait(1)

        def preview_worker():
            backend = BackendConnection(self.backend_url, self.token, self.device_id, self.timeout)
            sequence, heartbeat = 0, 0
            try:
                while not stop.is_set():
                    item = latest.get(sequence)
                    if item is None:
                        continue
                    sequence, image = item
                    start = time.monotonic()
                    try:
                        if start >= heartbeat:
                            backend.json("/devices/heartbeat", {"name": "ESP32-CAM · MJPEG bridge", "ip_address": urlparse(self.camera_url).hostname})
                            heartbeat = start + 10
                        backend.image(prefix + "/preview", image)
                    except (OSError, ValueError, http.client.HTTPException) as exc:
                        heartbeat = 0
                        LOG.warning("Preview upload failed: %s", exc)
                        stop.wait(1)
                    stop.wait(max(0, 1 / fps - (time.monotonic() - start)))
            finally:
                backend.close()

        def ai_worker():
            # Slow inference cannot block camera reading or preview upload.
            backend = BackendConnection(self.backend_url, self.token, self.device_id, max(30, self.timeout))
            sequence, next_config, config = 0, 0, {}
            last_message = None
            try:
                while not stop.is_set():
                    item = latest.get(sequence)
                    if item is None:
                        continue
                    sequence, image = item
                    start = time.monotonic()
                    try:
                        if start >= next_config:
                            config = backend.request("/devices/config")
                            next_config = start + 2
                        session = config.get("session_id")
                        if config.get("active") and isinstance(session, int) and session > 0:
                            newest = latest.get(after=-1, timeout=0)
                            if newest is None:
                                continue
                            sequence, image = newest
                            result = backend.image(prefix + f"/frames?session_id={session}", image)
                            message = ("accepted" if result.get("accepted") is True else "waiting", result.get("reason", "Backend confirmed attendance"))
                        else:
                            message = ("idle", "Live preview connected; assign an open session in dashboard")
                        if message != last_message:
                            LOG.info("%s: %s", *message)
                            last_message = message
                    except (OSError, ValueError, AttributeError, http.client.HTTPException) as exc:
                        config, next_config = {}, 0
                        LOG.warning("AI request not accepted: %s", exc)
                        stop.wait(1)
                    stop.wait(max(0, self.interval - (time.monotonic() - start)))
            finally:
                backend.close()

        threads = [threading.Thread(target=worker, daemon=True, name=name)
                   for worker, name in ((reader, "camera-reader"), (preview_worker, "preview"), (ai_worker, "sampled-ai"))]
        LOG.info("Low-latency %s: preview target %.0f FPS, AI interval %.2fs. Latest frames only; no queues.", mode, fps, self.interval)
        for thread in threads:
            thread.start()
        try:
            while not stop.wait(1):
                if any(not thread.is_alive() for thread in threads):
                    raise RuntimeError("Camera worker stopped unexpectedly; restart bridge")
        finally:
            stop.set()
            for thread in threads:
                thread.join(timeout=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env")
    parser.add_argument("--check", action="store_true", help="Check camera/backend once; no attendance uploaded")
    args = parser.parse_args()
    load_env(args.env_file)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        bridge = CameraBridge(
            os.getenv("CAMERA_CAPTURE_URL", "http://192.168.4.1:81/capture"),
            os.getenv("BRIDGE_BACKEND_URL", "http://127.0.0.1:" + os.getenv("BACKEND_PORT", "8000")),
            os.getenv("CAMERA_DEVICE_ID", "esp32-cam-01"), os.getenv("DEVICE_TOKEN", ""),
            float(os.getenv("CAMERA_INTERVAL_SECONDS", ".8")), float(os.getenv("CAMERA_TIMEOUT_SECONDS", "5")),
        )
        if args.check:
            image = bridge.capture()
            bridge.api("/devices/heartbeat", {"name": "ESP32-CAM · SoftAP bridge", "ip_address": urlparse(bridge.camera_url).hostname})
            config = bridge.api("/devices/config")
            LOG.info("Camera JPEG OK (%d bytes); backend/token OK; session=%s active=%s. No attendance uploaded.",
                     len(image), config.get("session_id"), config.get("active"))
        else:
            LOG.info("Streaming camera; Ctrl+C to stop. Close other camera viewers and old bridge processes.")
            bridge.run()
    except KeyboardInterrupt:
        LOG.info("Bridge stopped; no offline attendance is created")
    except (OSError, ValueError, URLError) as exc:
        parser.exit(1, f"Connection check failed: {exc}\n")


if __name__ == "__main__":
    main()
