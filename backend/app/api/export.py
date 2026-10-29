from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.attendance import _attendance_response
from app.core.security import verify_token
from app.database import get_db
from app.models import Attendance
from app.services.reporting import attendance_csv

router = APIRouter()


@router.get("/attendance/export")
def export_attendance(session_id: int | None = None, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    query = select(Attendance).order_by(Attendance.checked_at)
    if session_id is not None:
        query = query.where(Attendance.session_id == session_id)
    rows = [_attendance_response(item) for item in db.scalars(query)]
    return Response(
        content=attendance_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=attendance.csv"},
    )
