"""Database models for students, classes, sessions and audit events."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ClassRoom(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    students: Mapped[list["Student"]] = relationship(back_populates="classroom")
    sessions: Mapped[list["AttendanceSession"]] = relationship(back_populates="classroom")


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    date_of_birth: Mapped[str | None] = mapped_column(String(32), nullable=True)
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"), nullable=True)
    reference_dir: Mapped[str | None] = mapped_column(String(512), nullable=True)
    classroom: Mapped[ClassRoom | None] = relationship(back_populates="students")


class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    classroom: Mapped[ClassRoom] = relationship(back_populates="sessions")
    attendances: Mapped[list["Attendance"]] = relationship(back_populates="session")


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("session_id", "student_id", name="uq_session_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("attendance_sessions.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(32), default="present")
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verification: Mapped[str] = mapped_column(String(255), default="face+pad")
    session: Mapped[AttendanceSession] = relationship(back_populates="attendances")
    student: Mapped[Student] = relationship()


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="ESP32-CAM")
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(32), default="online")
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)


class FaceReference(Base):
    __tablename__ = "face_references"

    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), primary_key=True)
    embedding: Mapped[str] = mapped_column(Text)
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    enrolled_by: Mapped[str] = mapped_column(String(255))


class DeviceConfig(Base):
    __tablename__ = "device_configs"

    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("attendance_sessions.id"), nullable=True)
    roi_left: Mapped[float] = mapped_column(Float, default=0.22)
    roi_top: Mapped[float] = mapped_column(Float, default=0.15)
    roi_right: Mapped[float] = mapped_column(Float, default=0.78)
    roi_bottom: Mapped[float] = mapped_column(Float, default=0.85)


class LivenessEvent(Base):
    __tablename__ = "liveness_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("attendance_sessions.id"), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    student_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
