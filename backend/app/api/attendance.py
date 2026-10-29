from __future__ import annotations

import logging
import time
from functools import lru_cache

from starlette.concurrency import run_in_threadpool

from fastapi import APIRouter, Depends, Header, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import verify_device_token, verify_token
from app.database import get_db
from app.models import Attendance, AttendanceSession, Device, LivenessEvent, Student
from app.models.school import DeviceConfig, utcnow
from app.schemas import AttendanceResponse, LivenessEventResponse
from app.schemas.api import ManualAttendance
from app.services.antispoof import AntiSpoofAdapter
from app.services.face_detector import FaceDetector
from app.services.face_recognition import FaceRecognitionAdapter
from app.services.attendance_service import record_attendance
from app.services.stability import gate
from app.services.images import MAX_IMAGE_BYTES, validate_image
from app.services.websocket import manager
from app.services.camera_preview import previews

router = APIRouter()
logger = logging.getLogger(__name__)
last_frames = {}
processing_devices = set()


@lru_cache(maxsize=1)
def _detector():
    return FaceDetector()


@lru_cache(maxsize=1)
def _pad():
    return AntiSpoofAdapter()


@lru_cache(maxsize=1)
def _recognizer():
    return FaceRecognitionAdapter()


def _attendance_response(item):
    return dict(id=item.id, session_id=item.session_id, student_id=item.student_id,
                student_code=item.student.student_code, student_name=item.student.name,
                checked_at=item.checked_at, status=item.status, device_id=item.device_id,
                verification=item.verification)


async def event(db, session_id, device_id, result, reason, student_code=None):
    row = LivenessEvent(session_id=session_id, device_id=device_id, result=result,
                        reason=reason, student_code=student_code)
    db.add(row)
    db.commit()
    await manager.broadcast(session_id, {"type": "liveness", "result": result, "reason": reason})


@router.get("/attendance", response_model=list[AttendanceResponse])
def list_attendance(session_id: int | None = None, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    query = select(Attendance).order_by(Attendance.checked_at.desc())
    if session_id is not None:
        query = query.where(Attendance.session_id == session_id)
    return [_attendance_response(item) for item in db.scalars(query)]


@router.post("/devices/{device_id}/frames", status_code=202)
async def receive_frame(device_id: str, request: Request, image: UploadFile, session_id: int,
                        x_device_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    verify_device_token(x_device_token)
    if device_id in processing_devices:
        raise HTTPException(429, "A frame is already being processed for this device")
    processing_devices.add(device_id)
    try:
        return await _process_frame(device_id, image, session_id, db)
    finally:
        processing_devices.discard(device_id)


async def _process_frame(device_id, image, session_id, db):
    device = db.get(Device, device_id)
    config = db.get(DeviceConfig, device_id)
    if device is None or config is None or config.session_id != session_id:
        raise HTTPException(409, "Device is not assigned to this session")
    session = db.get(AttendanceSession, session_id)
    if session is None or session.status != "open":
        gate.reset((device_id, session_id))
        await event(db, session_id if session else None, device_id, "rejected", "Session is not open")
        raise HTTPException(409, "Attendance session is not open")
    now = time.monotonic()
    if now - last_frames.get(device_id, -100) < settings.frame_interval_seconds:
        raise HTTPException(429, "Frame rate exceeded", headers={"Retry-After": "1"})
    if len(last_frames) > 256:
        last_frames.clear()
    last_frames[device_id] = now
    if image.content_type not in {"image/jpeg", "image/png"}:
        raise HTTPException(415, "Only JPEG and PNG accepted")
    body = await image.read(MAX_IMAGE_BYTES + 1)
    if len(body) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image is too large")
    try:
        validate_image(body)
    except ValueError as exc:
        gate.reset((device_id, session_id))
        await event(db, session_id, device_id, "rejected", str(exc))
        return {"accepted": False, "reason": str(exc)}
    preview_sequence = previews.begin_analysis(device_id, body, session_id)
    def respond(result, detection=None):
        metadata = dict(result)
        if detection is not None:
            metadata["box"] = list(detection.box)
            metadata["frame_size"] = list(detection.frame_size)
        previews.update(device_id, preview_sequence, metadata)
        return result

    device.last_seen = utcnow()
    db.commit()
    roi = (config.roi_left, config.roi_top, config.roi_right, config.roi_bottom)
    key = (device_id, session_id)
    try:
        detection, reason = await run_in_threadpool(lambda: _detector().detect_largest(body, roi))
        if detection is None or reason != "ok":
            gate.reset(key)
            await event(db, session_id, device_id, "rejected", f"detector: {reason}")
            return respond({"accepted": False, "reason": reason}, detection)
        if not gate.observe(key, detection.box):
            return respond({"accepted": False, "reason": "waiting for stable face"}, detection)
        pad = await run_in_threadpool(lambda: _pad().evaluate(body, detection.box))
        if not pad.is_real:
            await event(db, session_id, device_id, "rejected", f"pad: {pad.reason}; real_score={pad.score}")
            return respond({"accepted": False, "reason": pad.reason, "pad_score": pad.score}, detection)
        recognition = await run_in_threadpool(lambda: _recognizer().recognize(body, detection.box, db, session.class_id))
        if recognition is None:
            await event(db, session_id, device_id, "rejected", "unknown, uncertain or unavailable identity")
            return respond({"accepted": False, "reason": "unknown, uncertain or unavailable identity"}, detection)
        student = db.scalar(select(Student).where(Student.student_code == recognition.student_code))
        row, created = record_attendance(db, session, student, device_id=device_id,
                                         verification=f"face+pad:{pad.score:.4f};distance:{recognition.distance:.4f}")
    except Exception:
        logger.exception("Attendance pipeline failed")
        db.rollback()
        gate.reset(key)
        await event(db, session_id, device_id, "error", "Pipeline failed; retry or use manual verification")
        return respond({"accepted": False, "reason": "Pipeline failed; retry or use manual verification"})
    await event(db, session_id, device_id, "accepted", "PAD and recognition passed", recognition.student_code)
    await manager.broadcast(session_id, {"type": "attendance", "created": created, "attendance_id": row.id})
    return respond({"accepted": True, "created": created, "student_code": recognition.student_code}, detection)


@router.post("/sessions/{session_id}/manual-attendance")
async def manual_attendance(session_id: int, payload: ManualAttendance,
                            username: str = Depends(verify_token), db: Session = Depends(get_db)):
    session, student = db.get(AttendanceSession, session_id), db.get(Student, payload.student_id)
    if session is None or student is None:
        raise HTTPException(404, "Session or student not found")
    try:
        row, created = record_attendance(db, session, student, device_id=None, verification=f"manual:{username}")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    await event(db, session_id, None, "manual", f"Verified by {username}: {payload.reason}", student.student_code)
    await manager.broadcast(session_id, {"type": "attendance", "created": created, "attendance_id": row.id})
    return {"created": created, "attendance": _attendance_response(row)}


@router.get("/liveness-events", response_model=list[LivenessEventResponse])
def list_events(session_id: int | None = None, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    query = select(LivenessEvent).order_by(LivenessEvent.id.desc()).limit(200)
    if session_id is not None:
        query = query.where(LivenessEvent.session_id == session_id)
    return list(db.scalars(query))


@router.get("/system/status")
def system_status(_: str = Depends(verify_token)):
    pad, recognizer = _pad(), _recognizer()
    return {"pad": {"ready": pad.ready, "loaded": pad.session is not None, "reason": pad.reason, "model": pad.model},
            "recognition": {"ready": recognizer.ready, "reason": recognizer.reason},
            "stable_frames": settings.stable_frames, "late_after_minutes": settings.late_after_minutes}
