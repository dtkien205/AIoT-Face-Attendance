import hmac

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import issue_token, verify_token
from app.core.config import settings
from app.database import get_db
from app.models import ClassRoom
from app.schemas import ClassCreate, ClassResponse, LoginRequest, TokenResponse

router = APIRouter()


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    if (
        not settings.admin_password
        or payload.username != settings.admin_username
        or not hmac.compare_digest(payload.password.encode(), settings.admin_password.encode())
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return TokenResponse(access_token=issue_token(payload.username))


@router.get("/classes", response_model=list[ClassResponse])
def list_classes(_: str = Depends(verify_token), db: Session = Depends(get_db)):
    return list(db.scalars(select(ClassRoom).order_by(ClassRoom.code)))


@router.post("/classes", response_model=ClassResponse, status_code=status.HTTP_201_CREATED)
def create_class(payload: ClassCreate, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    if db.scalar(select(ClassRoom).where(ClassRoom.code == payload.code)):
        raise HTTPException(status_code=409, detail="Class code already exists")
    classroom = ClassRoom(code=payload.code, name=payload.name)
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    return classroom


@router.put("/classes/{class_id}", response_model=ClassResponse)
def update_class(class_id: int, payload: ClassCreate, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    classroom = db.get(ClassRoom, class_id)
    if classroom is None:
        raise HTTPException(404, "Class not found")
    if db.scalar(select(ClassRoom).where(ClassRoom.code == payload.code, ClassRoom.id != class_id)):
        raise HTTPException(409, "Class code already exists")
    classroom.code, classroom.name = payload.code, payload.name
    db.commit()
    return classroom


@router.delete("/classes/{class_id}", status_code=204)
def delete_class(class_id: int, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    classroom = db.get(ClassRoom, class_id)
    if classroom is None:
        raise HTTPException(404, "Class not found")
    if classroom.students or classroom.sessions:
        raise HTTPException(409, "Class still contains students or sessions")
    db.delete(classroom)
    db.commit()
