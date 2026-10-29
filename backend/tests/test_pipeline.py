import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app.services.antispoof import AntiSpoofAdapter, prepare_face
from app.services.stability import StabilityGate
from app.services.reporting import attendance_csv


class PipelineTests(unittest.TestCase):
    def test_preprocessing_is_bgr_unnormalized(self):
        image = np.full((160, 160, 3), (10, 50, 200), dtype=np.uint8)
        _, data = cv2.imencode(".png", image)
        tensor = prepare_face(data.tobytes(), (40, 40, 80, 80))
        self.assertEqual(tensor.shape, (1, 3, 80, 80))
        self.assertEqual(tensor.dtype, np.float32)
        self.assertEqual(float(tensor[0, 0, 0, 0]), 10)
        self.assertEqual(float(tensor[0, 2, 0, 0]), 200)

    def test_invalid_face_box(self):
        _, data = cv2.imencode(".png", np.zeros((80, 80, 3), dtype=np.uint8))
        with self.assertRaises(ValueError):
            prepare_face(data.tobytes(), (0, 0, 0, 10))

    def test_stability_resets_on_motion_and_gap(self):
        gate = StabilityGate()
        self.assertFalse(gate.observe("cam", (0, 0, 100, 100), 0))
        self.assertFalse(gate.observe("cam", (1, 1, 100, 100), 1))
        self.assertTrue(gate.observe("cam", (2, 2, 100, 100), 2))
        self.assertFalse(gate.observe("cam", (100, 100, 100, 100), 3))
        self.assertFalse(gate.observe("cam", (100, 100, 100, 100), 10))

    def test_csv_formula_is_neutralized(self):
        report = attendance_csv([dict(checked_at="now", student_code="SV1", student_name="=1+1",
                                      status="present", verification="manual")]).decode("utf-8-sig")
        self.assertIn("'=1+1", report)

    def test_pad_missing_and_nan_fail_closed(self):
        adapter = AntiSpoofAdapter.__new__(AntiSpoofAdapter)
        adapter.session = None
        adapter.reason = "missing"
        self.assertFalse(adapter.evaluate(b"x", (1, 1, 1, 1)).is_real)
        from unittest.mock import Mock
        adapter.session = Mock()
        adapter.input_name, adapter.output_name = "input", "output"
        adapter.session.run.return_value = [np.array([[np.nan, 0, 0]])]
        with patch("app.services.antispoof.prepare_face", return_value=np.zeros((1, 3, 80, 80), np.float32)):
            self.assertEqual(adapter.evaluate(b"x", (1, 1, 1, 1)).reason, "invalid PAD output")


if __name__ == "__main__":
    unittest.main()
