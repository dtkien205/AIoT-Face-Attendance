from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InputModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class LoginRequest(InputModel):
    model_config = ConfigDict(str_strip_whitespace=False, extra="forbid")
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ClassCreate(InputModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)


class ClassResponse(ClassCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class StudentCreate(InputModel):
    student_code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=255)
    date_of_birth: str | None = Field(default=None, max_length=32)
    class_id: int | None = Field(default=None, gt=0)


class StudentResponse(StudentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    enrolled: bool = False


class SessionCreate(InputModel):
    class_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=255)


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    class_id: int
    title: str
    status: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class DeviceHeartbeat(InputModel):
    name: str = Field(default="ESP32-CAM", min_length=1, max_length=255)
    ip_address: str | None = Field(default=None, max_length=64)


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    status: str
    ip_address: str | None = None
    last_seen: datetime


class DeviceConfigInput(InputModel):
    session_id: int | None = Field(default=None, gt=0)
    roi_left: float = Field(default=0.22, ge=0, lt=1)
    roi_top: float = Field(default=0.15, ge=0, lt=1)
    roi_right: float = Field(default=0.78, gt=0, le=1)
    roi_bottom: float = Field(default=0.85, gt=0, le=1)

    @model_validator(mode="after")
    def valid_roi(self):
        if self.roi_left >= self.roi_right or self.roi_top >= self.roi_bottom:
            raise ValueError("ROI must have positive width and height")
        return self


class ManualAttendance(InputModel):
    student_id: int = Field(gt=0)
    reason: str = Field(min_length=5, max_length=500)


class AttendanceResponse(BaseModel):
    id: int
    session_id: int
    student_id: int
    student_code: str
    student_name: str
    checked_at: datetime
    status: str
    device_id: str | None
    verification: str


class LivenessEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    session_id: int | None
    device_id: str | None
    student_code: str | None
    result: str
    reason: str
    created_at: datetime
