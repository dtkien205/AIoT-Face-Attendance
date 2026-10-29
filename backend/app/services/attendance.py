"""Compatibility import; attendance rules live in one service."""
from app.services.attendance_service import record_attendance

__all__ = ["record_attendance"]
