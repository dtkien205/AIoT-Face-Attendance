"""Seed classes and students from the bundled roster JSON."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from app.core.domain import validate_roster
from app.database import SessionLocal, init_db
from app.models import ClassRoom, Student


ROOT = Path(__file__).resolve().parents[1]
ROSTER_PATH = ROOT / "data" / "class_roster.json"


def main() -> None:
    init_db()
    roster = validate_roster(json.loads(ROSTER_PATH.read_text(encoding="utf-8")))
    with SessionLocal() as db:
        classes = {item.code: item for item in db.scalars(select(ClassRoom))}
        for raw in roster:
            class_code = raw["class"]
            classroom = classes.get(class_code)
            if not classroom:
                classroom = ClassRoom(code=class_code, name=class_code)
                db.add(classroom)
                db.flush()
                classes[class_code] = classroom
            student_code = raw["id"].strip().upper()
            if not db.scalar(select(Student).where(Student.student_code == student_code)):
                db.add(Student(
                    student_code=student_code, name=raw["name"],
                    date_of_birth=raw.get("dob"), class_id=classroom.id,
                ))
        db.commit()
    print(f"Seeded {len(roster)} students")


if __name__ == "__main__":
    main()
