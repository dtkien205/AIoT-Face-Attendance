"""Pure unit tests for the domain rules; no optional AI dependencies required."""

import unittest
from pathlib import Path

from app.core.domain import (
    inside_roi,
    match_student_from_filename,
    remove_accents,
    select_largest_candidate,
    validate_roster,
)


ROSTER = [
    {"stt": 1, "id": "B23DCAT153", "name": "Nguyễn Đăng Khoa", "dob": "08/02/2005", "class": "D23CTAT01-B"},
    {"stt": 2, "id": "B23DCAT156", "name": "Đỗ Trung Kiên", "dob": "07/10/2005", "class": "D23CTAT01-B"},
    {"stt": 3, "id": "B23DCAT999", "name": "Nguyễn Đăng Khoa", "dob": "01/01/2005", "class": "D23CTAT01-B"},
]


class DomainTests(unittest.TestCase):
    def test_accents_are_normalized(self):
        self.assertEqual(remove_accents("Đỗ Trung Kiên"), "do trung kien")

    def test_roster_rejects_duplicate_ids(self):
        with self.assertRaises(ValueError):
            validate_roster([ROSTER[0], dict(ROSTER[0])])

    def test_filename_id_wins_over_duplicate_name(self):
        self.assertEqual(match_student_from_filename("B23DCAT999_Nguyen_Dang_Khoa.jpg", ROSTER)["id"], "B23DCAT999")

    def test_ambiguous_name_is_not_guessed(self):
        self.assertIsNone(match_student_from_filename("Nguyen_Dang_Khoa.jpg", ROSTER))

    def test_select_largest_candidate(self):
        self.assertEqual(select_largest_candidate([{"area": 10, "id": 1}, {"area": 20, "id": 2}])["id"], 2)

    def test_roi(self):
        self.assertTrue(inside_roi((50, 50), (100, 100), (0.2, 0.2, 0.8, 0.8)))
        self.assertFalse(inside_roi((5, 50), (100, 100), (0.2, 0.2, 0.8, 0.8)))


if __name__ == "__main__":
    unittest.main()
