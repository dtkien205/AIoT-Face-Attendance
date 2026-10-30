"""Small, explicitly labeled on-camera calibration sets; never store raw images."""
import hashlib
import json
import math
from datetime import timedelta

import numpy as np
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.attendance import _detector, _pad, _recognizer
from app.core.security import verify_token
from app.database import get_db
from app.models.school import CalibrationProfile, CameraTrial, Device, FaceReference, utcnow
from app.schemas.api import InputModel
from app.services.camera_preview import previews
from app.services.images import MAX_IMAGE_BYTES, validate_image

router = APIRouter()
LABELS = {"live", "replay", "same", "different"}
PAD_LABELS = {"live", "replay"}


class SampleInput(InputModel):
    label: str
    student_id: int | None = Field(default=None, gt=0)


class ApplyInput(InputModel):
    pad_threshold: float = Field(gt=0.5, lt=1)
    recognition_threshold: float = Field(gt=0, le=0.6)
    confirmed: bool


def report(profile):
    samples = json.loads(profile.samples) if profile else []
    counts = {label: sum(s["label"] == label for s in samples) for label in LABELS}
    pad_ready = all(counts[label] >= 3 for label in PAD_LABELS)
    rec_ready = all(counts[label] >= 3 for label in ("same", "different"))
    suggested_pad = suggested_rec = None
    if pad_ready:
        live = min(s["value"] for s in samples if s["label"] == "live")
        attack = max(s["value"] for s in samples if s["label"] == "replay")
        if live > max(0.5, attack) + .001:
            suggested_pad = (live + max(0.5, attack)) / 2
    if rec_ready:
        same = max(s["value"] for s in samples if s["label"] == "same")
        different = min(s["value"] for s in samples if s["label"] == "different")
        if same < min(different, .6) - .001:
            suggested_rec = (same + min(different, .6)) / 2
    return {"counts": counts, "samples": [{"label": s["label"], "value": s["value"]} for s in samples],
            "suggested_pad": suggested_pad, "suggested_recognition": suggested_rec,
            "pad_threshold": profile.pad_threshold if profile else None,
            "recognition_threshold": profile.recognition_threshold if profile else None,
            "applied_at": profile.applied_at if profile else None,
            "can_apply": suggested_pad is not None and suggested_rec is not None}


def get_profile(device_id, db):
    if db.get(Device, device_id) is None:
        raise HTTPException(404, "Camera chưa có trong hệ thống. Kết nối hoặc mở camera laptop trước.")
    profile = db.get(CalibrationProfile, device_id)
    if profile is None:
        profile = CalibrationProfile(device_id=device_id, samples="[]")
        db.add(profile)
    return profile


def add_sample(device_id, body, payload, db):
    if payload.label not in LABELS:
        raise HTTPException(422, "Nhãn mẫu không hợp lệ")
    profile = get_profile(device_id, db)
    samples = json.loads(profile.samples)
    if len(samples) >= 150:
        raise HTTPException(409, "Đã đủ 150 mẫu; xóa bộ mẫu để hiệu chỉnh lại")
    digest = hashlib.sha256(body).hexdigest()
    if any(s["digest"] == digest and (s["label"] in PAD_LABELS) == (payload.label in PAD_LABELS) for s in samples):
        raise HTTPException(409, "Ảnh này đã được lấy mẫu. Dùng khung hình khác, không đổi nhãn cùng một ảnh.")
    try:
        validate_image(body)
        if payload.label in PAD_LABELS:
            detection, reason = _detector().detect_largest(body, (0, 0, 1, 1))
            if detection is None or reason != "ok":
                raise ValueError(reason)
            result = _pad().evaluate(body, detection.box)
            if result.score is None:
                raise ValueError(result.reason)
            value = result.score
        else:
            reference = db.get(FaceReference, payload.student_id) if payload.student_id else None
            if reference is None:
                raise ValueError("Chọn sinh viên đã đăng ký khuôn mặt để đối chiếu")
            vector = np.asarray(json.loads(reference.embedding), dtype=np.float64)
            if vector.shape != (128,) or not np.isfinite(vector).all():
                raise ValueError("Embedding đăng ký không hợp lệ")
            value = float(np.linalg.norm(_recognizer().encode(body) - vector))
        if not math.isfinite(value):
            raise ValueError("Điểm mô hình không hợp lệ")
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    samples.append({"label": payload.label, "value": value, "digest": digest})
    profile.samples = json.dumps(samples)
    # New evidence invalidates any earlier approval for this camera.
    profile.pad_threshold = profile.recognition_threshold = None
    profile.applied_at = None
    db.commit()
    return report(profile)


class TrialInput(InputModel):
    confirmed: bool


@router.post("/calibration/{device_id}/trial")
def enable_trial(device_id: str, payload: TrialInput, username: str = Depends(verify_token), db: Session = Depends(get_db)):
    profile = get_profile(device_id, db)
    if not payload.confirmed or report(profile)["counts"]["live"] < 3:
        raise HTTPException(422, "Cần xác nhận thử nghiệm và ít nhất 3 mẫu người thật của camera này")
    if _pad().session is None or _recognizer().engine is None:
        raise HTTPException(503, "Cần nạp được cả mô hình PAD và nhận diện trước khi thử nghiệm")
    trial = db.get(CameraTrial, device_id)
    if trial is None:
        trial = CameraTrial(device_id=device_id)
        db.add(trial)
    trial.enabled_by = username
    trial.expires_at = utcnow() + timedelta(hours=2)
    db.commit()
    return {"trial": True, "expires_at": trial.expires_at, "pad_threshold": .9, "recognition_threshold": .52}


@router.delete("/calibration/{device_id}/trial", status_code=204)
def disable_trial(device_id: str, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    trial = db.get(CameraTrial, device_id)
    if trial:
        db.delete(trial)
        db.commit()


@router.get("/calibration/{device_id}")
def calibration_status(device_id: str, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    if db.get(Device, device_id) is None:
        raise HTTPException(404, "Camera chưa có trong hệ thống")
    return report(db.get(CalibrationProfile, device_id))


@router.post("/calibration/{device_id}/capture")
async def capture(device_id: str, payload: SampleInput, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    frame = previews.get(device_id)
    if frame is None:
        raise HTTPException(409, "Không có ảnh camera mới. Mở camera trước khi lấy mẫu.")
    return await run_in_threadpool(add_sample, device_id, frame["image"], payload, db)


@router.post("/calibration/{device_id}/upload")
async def upload(device_id: str, image: UploadFile, label: str = Form(...), student_id: int | None = Form(None),
                 _: str = Depends(verify_token), db: Session = Depends(get_db)):
    body = await image.read(MAX_IMAGE_BYTES + 1)
    if len(body) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Ảnh vượt quá 5 MiB")
    return await run_in_threadpool(add_sample, device_id, body, SampleInput(label=label, student_id=student_id), db)


@router.post("/calibration/{device_id}/apply")
def apply(device_id: str, payload: ApplyInput, username: str = Depends(verify_token), db: Session = Depends(get_db)):
    profile = get_profile(device_id, db)
    summary = report(profile)
    if not payload.confirmed or not summary["can_apply"]:
        raise HTTPException(422, "Cần ít nhất 3 mẫu cho mỗi nhóm và điểm giữa các nhóm phải tách biệt")
    samples = json.loads(profile.samples)
    pad_ok = all((s["value"] >= payload.pad_threshold) == (s["label"] == "live") for s in samples if s["label"] in PAD_LABELS)
    rec_ok = all((s["value"] <= payload.recognition_threshold) == (s["label"] == "same") for s in samples if s["label"] in {"same", "different"})
    if not pad_ok or not rec_ok:
        raise HTTPException(422, "Ngưỡng đã chọn phân loại sai bộ mẫu. Thu thêm mẫu hoặc chọn lại ngưỡng.")
    profile.pad_threshold, profile.recognition_threshold = payload.pad_threshold, payload.recognition_threshold
    profile.applied_by, profile.applied_at = username, utcnow()
    trial = db.get(CameraTrial, device_id)
    if trial:
        db.delete(trial)
    db.commit()
    return report(profile)


@router.delete("/calibration/{device_id}", status_code=204)
def reset(device_id: str, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    profile = db.get(CalibrationProfile, device_id)
    trial = db.get(CameraTrial, device_id)
    if trial:
        db.delete(trial)
    if profile:
        db.delete(profile)
    db.commit()
