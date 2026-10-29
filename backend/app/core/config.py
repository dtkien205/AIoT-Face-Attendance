"""Application settings loaded from environment variables and .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / "backend" / ".env")
DATA_DIR = Path(os.getenv("ATTENDANCE_DATA_DIR", ROOT_DIR / "data"))


@dataclass(frozen=True)
class Settings:
    app_name: str = "AIoT Face Attendance API"
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'attendance.db').as_posix()}")
    device_token: str = os.getenv("DEVICE_TOKEN", "")
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")
    recognition_threshold: float = float(os.getenv("RECOGNITION_THRESHOLD", "0.52"))
    recognition_margin: float = float(os.getenv("RECOGNITION_MARGIN", "0.05"))
    min_face_area_ratio: float = float(os.getenv("MIN_FACE_AREA_RATIO", "0.03"))
    min_sharpness: float = float(os.getenv("MIN_SHARPNESS", "25"))
    stable_frames: int = int(os.getenv("STABLE_FRAMES", "3"))
    stable_gap_seconds: float = float(os.getenv("STABLE_GAP_SECONDS", "3"))
    device_offline_seconds: int = int(os.getenv("DEVICE_OFFLINE_SECONDS", "45"))
    late_after_minutes: int = int(os.getenv("LATE_AFTER_MINUTES", "15"))
    frame_interval_seconds: float = float(os.getenv("FRAME_INTERVAL_SECONDS", "0.4"))
    preview_max_fps: int = max(1, min(30, int(os.getenv("PREVIEW_MAX_FPS", "20"))))
    pad_model_path: str = os.getenv("PAD_MODEL_PATH", "")
    pad_real_threshold: float = float(os.getenv("PAD_REAL_THRESHOLD", "0.9"))
    pad_crop_scale: float = float(os.getenv("PAD_CROP_SCALE", "2.7"))
    recognition_calibrated: bool = os.getenv("RECOGNITION_CALIBRATED", "false").lower() == "true"
    pad_calibrated: bool = os.getenv("PAD_CALIBRATED", "false").lower() == "true"
    cors_origins: tuple[str, ...] = tuple(
        origin.strip() for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:8080,http://127.0.0.1:8080,http://localhost:5173,http://127.0.0.1:5173",
        ).split(",") if origin.strip()
    )


settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
