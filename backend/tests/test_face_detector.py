import unittest
from unittest.mock import Mock, patch

import numpy as np

from app.services.face_detector import FaceDetector


class FaceDetectorTests(unittest.TestCase):
    def test_largest_face_inside_roi_is_selected(self):
        detector = FaceDetector.__new__(FaceDetector)
        detector.cascade = Mock()
        detector.cascade.detectMultiScale.return_value = np.asarray([
            (10, 10, 40, 40),
            (80, 60, 80, 80),
        ])
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        with patch("app.services.face_detector.cv2.imdecode", return_value=frame), \
             patch("app.services.face_detector.settings") as settings:
            settings.min_face_area_ratio = 0
            settings.min_sharpness = 0
            detection, reason = detector.detect_largest(b"image", (0, 0, 1, 1))
        self.assertEqual(reason, "ok")
        self.assertEqual(detection.box, (80, 60, 80, 80))


if __name__ == "__main__":
    unittest.main()
