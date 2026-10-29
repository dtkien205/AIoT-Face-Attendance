"""Short-lived geometric continuity gate; not proof of identity or direction."""
import time
from collections import OrderedDict

from app.core.config import settings


class StabilityGate:
    def __init__(self):
        self.tracks = OrderedDict()

    def reset(self, key):
        self.tracks.pop(key, None)

    def observe(self, key, box, now=None):
        now = time.monotonic() if now is None else now
        previous = self.tracks.pop(key, None)
        count = 1
        if previous:
            old, last, total = previous
            x, y, w, h = box
            ox, oy, ow, oh = old
            intersection = max(0, min(x+w, ox+ow)-max(x, ox)) * max(0, min(y+h, oy+oh)-max(y, oy))
            union = w*h + ow*oh - intersection
            if now-last <= settings.stable_gap_seconds and union > 0 and intersection/union >= 0.6:
                count = total + 1
        self.tracks[key] = (box, now, count)
        while len(self.tracks) > 256:
            self.tracks.popitem(last=False)
        return count >= max(1, settings.stable_frames)


gate = StabilityGate()
