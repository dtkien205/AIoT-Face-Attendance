"""Small, dependency-free domain helpers shared by the API and tests."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from pathlib import Path

REQUIRED_STUDENT_FIELDS = ("stt", "id", "name", "dob", "class")


def remove_accents(value: object) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFD", str(value))
    without_marks = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    return without_marks.replace("đ", "d").replace("Đ", "D").lower().strip()


def validate_roster(roster: object) -> list[dict]:
    if not isinstance(roster, list):
        raise ValueError("Roster must be a JSON array")

    normalized: list[dict] = []
    seen_ids: set[str] = set()
    for index, raw_student in enumerate(roster, start=1):
        if not isinstance(raw_student, Mapping):
            raise ValueError(f"Roster item {index} is not an object")
        missing = [field for field in REQUIRED_STUDENT_FIELDS if not raw_student.get(field)]
        if missing:
            raise ValueError(f"Roster item {index} is missing: {', '.join(missing)}")
        student = dict(raw_student)
        student_id = str(student["id"]).strip().upper()
        if student_id in seen_ids:
            raise ValueError(f"Duplicate student ID: {student_id}")
        seen_ids.add(student_id)
        student["id"] = student_id
        student["name"] = str(student["name"]).strip()
        student["class"] = str(student["class"]).strip()
        normalized.append(student)
    return normalized


def match_student_from_filename(filename: str | Path, roster: Iterable[Mapping]) -> Mapping | None:
    stem = Path(filename).stem
    upper_stem = stem.upper()
    for student in roster:
        student_id = str(student.get("id", "")).strip().upper()
        if student_id and student_id in upper_stem:
            return student

    name_stem = re.sub(r"_\d+$", "", stem).replace("_", " ")
    normalized_name = remove_accents(name_stem)
    matches = [
        student for student in roster
        if remove_accents(student.get("name", "")) == normalized_name
    ]
    return matches[0] if len(matches) == 1 else None


def select_largest_candidate(candidates: Iterable[Mapping]) -> Mapping | None:
    return max(list(candidates), key=lambda candidate: candidate.get("area", 0), default=None)


def inside_roi(
    center: tuple[float, float],
    frame_size: tuple[int, int],
    roi: tuple[float, float, float, float] = (0.22, 0.15, 0.78, 0.85),
) -> bool:
    width, height = frame_size
    if width <= 0 or height <= 0:
        return False
    x, y = center
    left, top, right, bottom = roi
    return left * width <= x <= right * width and top * height <= y <= bottom * height
