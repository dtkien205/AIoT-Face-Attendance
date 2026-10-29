import asyncio

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.database import get_db
from app.models import AttendanceSession
from app.services.websocket import manager

router = APIRouter()


@router.websocket("/ws/sessions/{session_id}")
async def session_events(websocket: WebSocket, session_id: int, db: Session = Depends(get_db)):
    await websocket.accept()
    try:
        auth = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        if not isinstance(auth, dict) or not isinstance(auth.get("token"), str):
            raise ValueError("Invalid authentication message")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth["token"])
        verify_token(credentials)
        if db.get(AttendanceSession, session_id) is None:
            await websocket.close(code=4404)
            return
        db.rollback()
        manager.register(session_id, websocket, credentials)
        await websocket.send_json({"type": "ready"})
        while True:
            await asyncio.wait_for(websocket.receive_text(), timeout=60)
            verify_token(credentials)
    except (HTTPException, ValueError, TypeError, asyncio.TimeoutError):
        await websocket.close(code=4401)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(session_id, websocket)


@router.websocket("/ws/devices/{device_id}/camera")
async def camera_stream(websocket: WebSocket, device_id: str, db: Session = Depends(get_db)):
    from app.models import Device
    from app.services.camera_preview import previews

    await websocket.accept()
    listener = None
    try:
        auth = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        if not isinstance(auth, dict) or not isinstance(auth.get("token"), str):
            raise ValueError("Invalid authentication")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth["token"])
        verify_token(credentials)
        if db.get(Device, device_id) is None:
            await websocket.close(code=4404)
            return
        db.rollback()
        listener = previews.subscribe(device_id)
        sequence = -1
        while True:
            verify_token(credentials)
            listener.clear()
            frame = previews.get(device_id)
            if frame and frame["sequence"] != sequence:
                sequence = frame["sequence"]
                await asyncio.wait_for(websocket.send_bytes(frame["image"]), timeout=3)
                # Browser ACK only after decode/display. At most one frame in
                # flight; a slow viewer skips frames instead of accumulating lag.
                message = await asyncio.wait_for(websocket.receive_text(), timeout=10)
                if message != "next":
                    raise ValueError("Expected frame acknowledgement")
            else:
                try:
                    await asyncio.wait_for(listener.wait(), timeout=1)
                except asyncio.TimeoutError:
                    if previews.get(device_id) is None:
                        await asyncio.wait_for(websocket.send_json({"type": "waiting"}), timeout=3)
    except asyncio.TimeoutError:
        await websocket.close(code=1013)
    except (HTTPException, ValueError, TypeError):
        await websocket.close(code=4401)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if listener is not None:
            previews.unsubscribe(device_id, listener)
