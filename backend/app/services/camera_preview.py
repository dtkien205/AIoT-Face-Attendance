"""Latest-frame RAM buffer, independent from sampled AI results; no frame queues."""
import asyncio
import time
from collections import OrderedDict
from datetime import datetime, timezone


class PreviewStore:
    def __init__(self, ttl=5, capacity=8):
        self.ttl, self.capacity = ttl, capacity
        self.frames = OrderedDict()
        self.results = OrderedDict()
        self.sequence = 0
        self.listeners = {}

    def _expire(self):
        now = time.monotonic()
        for key, value in list(self.frames.items()):
            if now - value["time"] > self.ttl:
                self.frames.pop(key, None)
        for key, value in list(self.results.items()):
            if now - value["time"] > self.ttl:
                self.results.pop(key, None)

    def subscribe(self, device_id):
        event = asyncio.Event()
        self.listeners.setdefault(device_id, set()).add(event)
        return event

    def unsubscribe(self, device_id, event):
        group = self.listeners.get(device_id)
        if group is not None:
            group.discard(event)
            if not group:
                self.listeners.pop(device_id, None)

    def put(self, device_id, image, session_id=None):
        self._expire()
        self.sequence += 1
        self.frames.pop(device_id, None)
        self.frames[device_id] = {
            "sequence": self.sequence, "time": time.monotonic(), "image": image,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id, "result": {"state": "processing" if session_id else "preview"},
        }
        while len(self.frames) > self.capacity:
            self.frames.popitem(last=False)
        for listener in self.listeners.get(device_id, ()):
            listener.set()
        return self.sequence

    def begin_analysis(self, device_id, image, session_id):
        # Push-only firmware still has preview; a sampled older frame must not
        # replace an already flowing independent video frame.
        current = self.get(device_id)
        if current is None or current["session_id"] is not None:
            self.put(device_id, image, session_id)
        self.sequence += 1
        sequence = self.sequence
        self.results[device_id] = {
            "sequence": sequence, "time": time.monotonic(), "session_id": session_id,
            "result": {"state": "processing"},
        }
        self.results.move_to_end(device_id)
        while len(self.results) > self.capacity:
            self.results.popitem(last=False)
        return sequence

    def update(self, device_id, sequence, result):
        analysis = self.results.get(device_id)
        if analysis and analysis["sequence"] == sequence:
            analysis["result"] = result
            analysis["time"] = time.monotonic()
        frame = self.frames.get(device_id)
        if frame and frame["sequence"] == sequence:
            frame["result"] = result

    def get(self, device_id):
        self._expire()
        return self.frames.get(device_id)

    def metadata(self, device_id):
        frame = self.get(device_id)
        if frame is None:
            return {"available": False}
        metadata = {key: value for key, value in frame.items() if key not in {"image", "time"}}
        analysis = self.results.get(device_id)
        if analysis:
            metadata.update(session_id=analysis["session_id"], result=analysis["result"],
                            result_age_seconds=round(time.monotonic() - analysis["time"], 2))
        return {**metadata, "available": True}


previews = PreviewStore()
