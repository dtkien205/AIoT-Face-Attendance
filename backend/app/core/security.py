"""Minimal signed bearer authentication for the local prototype."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings


bearer = HTTPBearer(auto_error=False)


def _signature(payload: str) -> str:
    return hmac.new(
        settings.admin_password.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()


def issue_token(username: str) -> str:
    payload = f"{username}:{int(time.time()) + 8 * 3600}"
    encoded = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{encoded}.{_signature(encoded)}"


def verify_token(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    if not settings.admin_password:
        raise HTTPException(status_code=503, detail="Administrator password is not configured")
    try:
        encoded, supplied_signature = credentials.credentials.split(".", 1)
        expected = _signature(encoded)
        if not hmac.compare_digest(expected, supplied_signature):
            raise ValueError
        payload = base64.urlsafe_b64decode(encoded + "===").decode()
        username, expiry = payload.rsplit(":", 1)
        if username != settings.admin_username or int(expiry) < int(time.time()):
            raise ValueError
        return username
    except (ValueError, TypeError, UnicodeError, base64.binascii.Error):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


def verify_device_token(token: str | None) -> None:
    if not token or not settings.device_token or not hmac.compare_digest(token.encode(), settings.device_token.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device token")
