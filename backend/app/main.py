from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import attendance, auth, calibration, devices, export, sessions, students, websocket
from app.core.config import settings
from app.database import init_db
from app.services.bridge_control import bridge


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(application):
        init_db()
        try:
            yield
        finally:
            bridge.stop()

    application = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(auth.router, prefix="/api")
    application.include_router(students.router, prefix="/api")
    application.include_router(sessions.router, prefix="/api")
    application.include_router(devices.router, prefix="/api")
    application.include_router(attendance.router, prefix="/api")
    application.include_router(calibration.router, prefix="/api")
    application.include_router(export.router, prefix="/api")
    application.include_router(websocket.router)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
