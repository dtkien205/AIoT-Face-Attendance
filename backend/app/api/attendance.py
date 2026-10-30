from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict
from datetime import timedelta, timezone
from functools import lru_cache

from starlette.concurrency import run_in_threadpool

from fastapi import APIRouter, Depends, Header, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import verify_device_token, verify_token
from app.database import get_db
from app.models import Attendance, AttendanceSession, Device, LivenessEvent, Student
from app.models.school import CalibrationProfile, CameraTrial, DeviceConfig, utcnow
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


@router.get("/attendance/analytics")
def attendance_analytics(class_id: int | None = None, session_id: int | None = None,
                         _: str = Depends(verify_token), db: Session = Depends(get_db)):
    session_query = select(AttendanceSession).where(AttendanceSession.starts_at.is_not(None))
    if class_id is not None:
        session_query = session_query.where(AttendanceSession.class_id == class_id)
    if session_id is not None:
        session_query = session_query.where(AttendanceSession.id == session_id)
    sessions = list(db.scalars(session_query.order_by(AttendanceSession.starts_at)))
    students = list(db.scalars(select(Student).where(Student.class_id.is_not(None))))
    session_ids = {item.id for item in sessions}
    attendances = list(db.scalars(select(Attendance).where(Attendance.session_id.in_(session_ids)))) if session_ids else []

    students_by_class = defaultdict(list)
    for student in students:
        students_by_class[student.class_id].append(student)
    attendance_by_session = defaultdict(list)
    attended_sessions_by_student = defaultdict(set)
    for row in attendances:
        attendance_by_session[row.session_id].append(row)
        attended_sessions_by_student[row.student_id].add(row.session_id)

    weekly = defaultdict(lambda: {"attended": 0, "possible": 0, "sessions": 0})
    sessions_by_class = defaultdict(list)
    for item in sessions:
        starts_at = item.starts_at
        week_start = starts_at.date() - timedelta(days=starts_at.weekday())
        bucket = weekly[week_start.isoformat()]
        bucket["sessions"] += 1
        bucket["possible"] += len(students_by_class[item.class_id])
        bucket["attended"] += len(attendance_by_session[item.id])
        sessions_by_class[item.class_id].append(item.id)

    weekly_rows = []
    for week_start, values in sorted(weekly.items()):
        possible = values["possible"]
        weekly_rows.append({"week_start": week_start, **values,
                            "rate": round(values["attended"] * 100 / possible, 1) if possible else 0})

    warnings = []
    threshold = 75.0
    for student in students:
        class_sessions = sessions_by_class[student.class_id]
        if not class_sessions:
            continue
        attended = len(attended_sessions_by_student[student.id].intersection(class_sessions))
        rate = round(attended * 100 / len(class_sessions), 1)
        if rate < threshold:
            warnings.append({"student_id": student.id, "student_code": student.student_code,
                             "student_name": student.name, "attended": attended,
                             "sessions": len(class_sessions), "rate": rate})
    warnings.sort(key=lambda item: (item["rate"], item["student_code"]))

    total_possible = sum(item["possible"] for item in weekly_rows)
    late_count = sum(row.status == "late" for row in attendances)
    return {"weekly": weekly_rows, "low_attendance": warnings, "threshold": threshold,
            "summary": {"sessions": len(sessions), "attended": len(attendances),
                        "possible": total_possible,
                        "attendance_rate": round(len(attendances) * 100 / total_possible, 1) if total_possible else 0,
                        "late_count": late_count,
                        "late_rate": round(late_count * 100 / len(attendances), 1) if attendances else 0}}


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


@router.post("/browser-camera/frames", status_code=202)
async def browser_frame(image: UploadFile, session_id: int, username: str = Depends(verify_token), db: Session = Depends(get_db)):
    session = db.get(AttendanceSession, session_id)
    if session is None or session.status != "open":
        raise HTTPException(409, "Chọn buổi điểm danh đang mở trước khi quét camera laptop")
    device_id = "browser-cam-" + hashlib.sha256(username.encode()).hexdigest()[:16]
    if device_id in processing_devices:
        raise HTTPException(429, "Camera đang xử lý ảnh trước")
    processing_devices.add(device_id)
    try:
        device = db.get(Device, device_id)
        if device is None:
            device = Device(id=device_id, name="Camera laptop", last_seen=utcnow(), status="online")
            db.add(device)
            db.flush()
        config = db.get(DeviceConfig, device_id)
        if config is None:
            config = DeviceConfig(device_id=device_id, roi_left=0, roi_top=0, roi_right=1, roi_bottom=1)
            db.add(config)
        if config.session_id != session_id:
            gate.reset((device_id, config.session_id))
            gate.reset((device_id, session_id))
            config.session_id = session_id
        db.commit()
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
        return metadata

    device.last_seen = utcnow()
    db.commit()
    roi = (config.roi_left, config.roi_top, config.roi_right, config.roi_bottom)
    key = (device_id, session_id)
    try:
        candidates, reason = await run_in_threadpool(lambda: _detector().detect_candidates(body, roi))
        if not candidates:
            gate.reset(key)
            await event(db, session_id, device_id, "rejected", f"detector: {reason}")
            return respond({"accepted": False, "reason": reason})
        profile = db.get(CalibrationProfile, device_id, populate_existing=True)
        calibrated = profile is not None and profile.applied_at is not None
        pad_options = {"threshold": profile.pad_threshold} if calibrated else {}
        recognition_options = {"threshold": profile.recognition_threshold} if calibrated else {}
        trial = db.get(CameraTrial, device_id, populate_existing=True)
        trial_active = not calibrated and trial is not None and trial.expires_at.replace(tzinfo=timezone.utc) > utcnow()
        if trial_active:
            pad_options = {"threshold": .9}
            recognition_options = {"threshold": .52}
        attended_ids = set(db.scalars(select(Attendance.student_id).where(Attendance.session_id == session_id)))
        chosen = fallback = failure = None
        for detection, candidate_reason in candidates:
            if candidate_reason != "ok":
                failure = failure or ({"accepted": False, "reason": candidate_reason}, f"detector: {candidate_reason}", detection)
                continue
            if not gate.observe(key, detection.box):
                failure = failure or ({"accepted": False, "reason": "waiting for stable face"}, "waiting for stable face", detection)
                continue
            pad = await run_in_threadpool(lambda box=detection.box: _pad().evaluate(body, box, **pad_options))
            if not pad.is_real:
                failure = failure or ({"accepted": False, "reason": pad.reason, "pad_score": pad.score},
                                      f"pad: {pad.reason}; real_score={pad.score}", detection)
                continue
            recognition = await run_in_threadpool(lambda box=detection.box: _recognizer().recognize(body, box, db, session.class_id, **recognition_options))
            if recognition is None:
                failure = failure or ({"accepted": False, "reason": "unknown, uncertain or unavailable identity"},
                                      "unknown, uncertain or unavailable identity", detection)
                continue
            student = db.scalar(select(Student).where(Student.student_code == recognition.student_code))
            match = (detection, pad, recognition, student)
            if student.id not in attended_ids:
                chosen = match
                break
            fallback = fallback or match
        chosen = chosen or fallback
        if chosen is None:
            payload, event_reason, failed_detection = failure or ({"accepted": False, "reason": "unknown, uncertain or unavailable identity"}, "unknown, uncertain or unavailable identity", candidates[0][0])
            await event(db, session_id, device_id, "rejected", event_reason)
            return respond(payload, failed_detection)
        detection, pad, recognition, student = chosen
        row, created = record_attendance(db, session, student, device_id=device_id,
                                         verification=f"{'trial:' if trial_active else ''}face+pad:{pad.score:.4f};distance:{recognition.distance:.4f}")
    except Exception:
        logger.exception("Attendance pipeline failed")
        db.rollback()
        gate.reset(key)
        await event(db, session_id, device_id, "error", "Pipeline failed; retry or use manual verification")
        return respond({"accepted": False, "reason": "Pipeline failed; retry or use manual verification"})
    await event(db, session_id, device_id, "accepted", "PAD and recognition passed", recognition.student_code)
    await manager.broadcast(session_id, {"type": "attendance", "created": created, "attendance_id": row.id})
    return respond({"accepted": True, "created": created, "student_code": recognition.student_code,
                    "student_name": student.name, "trial": trial_active}, detection)


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
def system_status(_: str = Depends(verify_token), db: Session = Depends(get_db)):
    pad, recognizer = _pad(), _recognizer()
    calibrated = [row.device_id for row in db.scalars(select(CalibrationProfile).where(CalibrationProfile.applied_at.is_not(None)))]
    calibrated_set = set(calibrated)
    return {"pad": {"ready": pad.ready, "loaded": pad.session is not None, "reason": pad.reason, "model": pad.model},
            "recognition": {"ready": recognizer.ready, "reason": recognizer.reason},
            "calibrated_devices": calibrated,
            "trial_devices": [row.device_id for row in db.scalars(select(CameraTrial))
                              if row.device_id not in calibrated_set and row.expires_at.replace(tzinfo=timezone.utc) > utcnow()],
            "stable_frames": settings.stable_frames, "late_after_minutes": settings.late_after_minutes}
