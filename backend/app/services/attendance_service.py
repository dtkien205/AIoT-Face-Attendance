"""SQLite write transaction serializes attendance against session close."""
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models import Attendance, AttendanceSession, Student
from app.models.school import DeviceConfig, FaceReference, SessionPause


def record_attendance(db, session, student, *, device_id, verification):
    session_id, student_id = session.id, student.id
    db.rollback()
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    session = db.get(AttendanceSession, session_id, populate_existing=True)
    student = db.get(Student, student_id, populate_existing=True)
    if session is None or session.status != "open":
        db.rollback()
        raise ValueError("Attendance session is not open")
    if student is None or student.class_id != session.class_id:
        db.rollback()
        raise ValueError("Student does not belong to this class")
    if device_id is not None:
        config = db.get(DeviceConfig, device_id, populate_existing=True)
        reference = db.get(FaceReference, student_id, populate_existing=True)
        if config is None or config.session_id != session_id or reference is None:
            db.rollback()
            raise ValueError("Device assignment or biometric enrollment changed; retry verification")
    existing = db.scalar(select(Attendance).where(Attendance.session_id == session_id, Attendance.student_id == student_id))
    if existing:
        db.commit()
        return existing, False
    now = datetime.now(timezone.utc)
    start = session.starts_at.replace(tzinfo=timezone.utc) if session.starts_at else now
    paused = sum((pause.resumed_at.replace(tzinfo=timezone.utc) - pause.paused_at.replace(tzinfo=timezone.utc)
                  for pause in db.scalars(select(SessionPause).where(SessionPause.session_id == session_id))), timedelta())
    row = Attendance(session_id=session_id, student_id=student_id, checked_at=now,
                     status="late" if now > start + paused + timedelta(minutes=settings.late_after_minutes) else "present",
                     device_id=device_id, verification=verification)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Attendance).where(Attendance.session_id == session_id, Attendance.student_id == student_id))
        if existing:
            return existing, False
        raise
    return row, True
