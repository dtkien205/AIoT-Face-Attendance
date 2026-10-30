from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text

from app.services.websocket import manager
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.database import get_db
from app.models import AttendanceSession, ClassRoom
from app.schemas import SessionCreate, SessionResponse
from app.models.school import SessionPause
from app.services.stability import gate

router = APIRouter()


@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(_: str = Depends(verify_token), db: Session = Depends(get_db)):
    return list(db.scalars(select(AttendanceSession).order_by(AttendanceSession.id.desc())))


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreate, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    if not db.get(ClassRoom, payload.class_id):
        raise HTTPException(status_code=404, detail="Class not found")
    session = AttendanceSession(class_id=payload.class_id, title=payload.title, status="draft")
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _set_status(session_id: int, target: str, db: Session) -> AttendanceSession:
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    session = db.get(AttendanceSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    now = datetime.now(timezone.utc)
    if target == "open":
        if session.status == "closed":
            if session.ends_at is None:
                raise HTTPException(status_code=409, detail="Missing close time; cannot resume session safely")
            db.add(SessionPause(session_id=session.id, paused_at=session.ends_at, resumed_at=now))
            session.ends_at = None
        session.status = "open"
        session.starts_at = session.starts_at or now
    else:
        if session.status != "open":
            raise HTTPException(status_code=409, detail="Only an open session can be closed")
        session.status = "closed"
        session.ends_at = now
    db.commit()
    for key in list(gate.tracks):
        if key[1] == session_id:
            gate.reset(key)
    db.refresh(session)
    return session


@router.post("/sessions/{session_id}/start", response_model=SessionResponse)
async def start_session(session_id: int, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    session = _set_status(session_id, "open", db)
    await manager.broadcast(session_id, {"type": "session", "status": "open"})
    return session


@router.post("/sessions/{session_id}/close", response_model=SessionResponse)
async def close_session(session_id: int, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    session = _set_status(session_id, "closed", db)
    await manager.broadcast(session_id, {"type": "session", "status": "closed"})
    return session
