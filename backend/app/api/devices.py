from datetime import datetime, timezone

import time
from starlette.concurrency import run_in_threadpool

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile
from fastapi.responses import Response

from app.services.camera_preview import previews
from app.services.images import MAX_IMAGE_BYTES, validate_image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import verify_device_token, verify_token
from app.database import get_db
from app.models import AttendanceSession, Device
from app.models.school import DeviceConfig
from app.schemas import DeviceHeartbeat, DeviceResponse
from app.schemas.api import DeviceConfigInput
from app.services.stability import gate

router = APIRouter()


def config_response(device_id, db):
    config = db.get(DeviceConfig, device_id)
    values = {key: getattr(config, key) for key in DeviceConfigInput.model_fields} if config else DeviceConfigInput().model_dump()
    session = db.get(AttendanceSession, values["session_id"]) if values["session_id"] else None
    return {**values, "active": session is not None and session.status == "open"}


@router.post("/devices/heartbeat", response_model=DeviceResponse)
def heartbeat(payload: DeviceHeartbeat, x_device_token: str | None = Header(default=None),
              x_device_id: str = Header(min_length=1, max_length=64), db: Session = Depends(get_db)):
    verify_device_token(x_device_token)
    device = db.get(Device, x_device_id)
    if device is None:
        device = Device(id=x_device_id)
        db.add(device)
    device.name, device.ip_address = payload.name, payload.ip_address
    device.last_seen = datetime.now(timezone.utc)
    device.status = "online"
    db.commit()
    return device


@router.get("/devices", response_model=list[DeviceResponse])
def list_devices(_: str = Depends(verify_token), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    rows = []
    for device in db.scalars(select(Device).order_by(Device.id)):
        last = device.last_seen.replace(tzinfo=timezone.utc)
        rows.append(dict(id=device.id, name=device.name, ip_address=device.ip_address,
                         last_seen=device.last_seen,
                         status="online" if (now-last).total_seconds() <= settings.device_offline_seconds else "offline"))
    return rows


@router.get("/devices/config")
def device_config(x_device_token: str | None = Header(default=None),
                  x_device_id: str = Header(min_length=1, max_length=64), db: Session = Depends(get_db)):
    verify_device_token(x_device_token)
    if db.get(Device, x_device_id) is None:
        raise HTTPException(404, "Send heartbeat first")
    return config_response(x_device_id, db)


@router.get("/devices/{device_id}/config")
def get_config(device_id: str, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    if db.get(Device, device_id) is None:
        raise HTTPException(404, "Device not found")
    return config_response(device_id, db)


@router.put("/devices/{device_id}/config")
def set_config(device_id: str, payload: DeviceConfigInput, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    if db.get(Device, device_id) is None:
        raise HTTPException(404, "Device not found")
    if payload.session_id and db.get(AttendanceSession, payload.session_id) is None:
        raise HTTPException(404, "Session not found")
    config = db.get(DeviceConfig, device_id)
    if config is None:
        config = DeviceConfig(device_id=device_id)
        db.add(config)
    old_session = config.session_id
    for key, value in payload.model_dump().items():
        setattr(config, key, value)
    db.commit()
    gate.reset((device_id, old_session))
    gate.reset((device_id, payload.session_id))
    return config_response(device_id, db)


preview_uploads = {}


@router.post("/devices/{device_id}/preview", status_code=202)
async def upload_preview(device_id: str, image: UploadFile,
                         x_device_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    verify_device_token(x_device_token)
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(404, "Send heartbeat first")
    now = time.monotonic()
    if now - preview_uploads.get(device_id, -100) < 1 / settings.preview_max_fps:
        raise HTTPException(429, "Preview rate exceeded")
    if len(preview_uploads) > 256:
        preview_uploads.clear()
    preview_uploads[device_id] = now
    if image.content_type not in {"image/jpeg", "image/png"}:
        raise HTTPException(415, "Only JPEG and PNG accepted")
    body = await image.read(MAX_IMAGE_BYTES + 1)
    if len(body) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image is too large")
    try:
        await run_in_threadpool(validate_image, body)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    previews.put(device_id, body)
    # Heartbeat updates database separately; no SQLite write per preview frame.
    return {"preview": True, "accepted": False, "reason": "Preview only; no attendance processed"}


@router.get("/devices/{device_id}/preview")
def preview_metadata(device_id: str, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    if db.get(Device, device_id) is None:
        raise HTTPException(404, "Device not found")
    config = config_response(device_id, db)
    metadata = previews.metadata(device_id)
    if not config["active"] or metadata.get("session_id") != config["session_id"]:
        metadata["result"] = {"state": "preview"}
    return {**metadata, "config": config}


@router.get("/devices/{device_id}/preview.jpg")
def preview_image(device_id: str, _: str = Depends(verify_token)):
    frame = previews.get(device_id)
    if frame is None:
        raise HTTPException(404, "No recent camera frame")
    image = frame["image"]
    return Response(image, media_type="image/png" if image.startswith(b"\x89PNG") else "image/jpeg",
                    headers={"Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff"})
