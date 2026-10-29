"""Single-worker WebSocket fan-out with expiry checks and bounded sends."""
import asyncio
from collections import defaultdict

from fastapi import HTTPException

from app.core.security import verify_token


class ConnectionManager:
    def __init__(self):
        self.connections = defaultdict(dict)

    def register(self, session_id, websocket, credentials):
        self.connections[session_id][websocket] = credentials

    def disconnect(self, session_id, websocket):
        group = self.connections.get(session_id)
        if group is not None:
            group.pop(websocket, None)
            if not group:
                self.connections.pop(session_id, None)

    async def broadcast(self, session_id, message):
        for websocket, credentials in list(self.connections.get(session_id, {}).items()):
            try:
                verify_token(credentials)
                await asyncio.wait_for(websocket.send_json(message), timeout=2)
            except Exception:
                self.disconnect(session_id, websocket)
                try:
                    await asyncio.wait_for(websocket.close(code=4401), timeout=1)
                except Exception:
                    pass


manager = ConnectionManager()
