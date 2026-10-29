import json

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.database import get_db
from app.models import Attendance, ClassRoom, Student
from app.models.school import FaceReference
from app.schemas import StudentCreate, StudentResponse
from app.services.face_recognition import FaceRecognitionAdapter
from app.services.images import validate_image
from starlette.concurrency import run_in_threadpool

router = APIRouter()


def student_response(student, db):
    return dict(id=student.id, student_code=student.student_code, name=student.name,
                date_of_birth=student.date_of_birth, class_id=student.class_id,
                enrolled=db.get(FaceReference, student.id) is not None)


def save_student(payload, db, student=None):
    if payload.class_id is not None and not db.get(ClassRoom, payload.class_id):
        raise HTTPException(404, "Class not found")
    values = payload.model_dump()
    values["student_code"] = values["student_code"].upper()
    if student is None:
        student = Student(**values)
        db.add(student)
    else:
        for key, value in values.items():
            setattr(student, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Student code already exists")
    return student_response(student, db)


@router.get("/students", response_model=list[StudentResponse])
def list_students(_: str = Depends(verify_token), db: Session = Depends(get_db)):
    return [student_response(s, db) for s in db.scalars(select(Student).order_by(Student.student_code))]


@router.post("/students", response_model=StudentResponse, status_code=201)
def create_student(payload: StudentCreate, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    return save_student(payload, db)


@router.put("/students/{student_id}", response_model=StudentResponse)
def update_student(student_id: int, payload: StudentCreate, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(404, "Student not found")
    return save_student(payload, db, student)


@router.delete("/students/{student_id}", status_code=204)
def delete_student(student_id: int, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(404, "Student not found")
    if db.scalar(select(Attendance.id).where(Attendance.student_id == student_id)):
        raise HTTPException(409, "Student has attendance history; delete biometric reference instead")
    reference = db.get(FaceReference, student_id)
    if reference:
        db.delete(reference)
        db.flush()
    db.delete(student)
    db.commit()


@router.post("/students/{student_id}/face")
async def enroll_face(student_id: int, image: UploadFile, consent: bool = Form(...),
                      username: str = Depends(verify_token), db: Session = Depends(get_db)):
    if not consent:
        raise HTTPException(422, "Explicit biometric consent is required")
    if db.get(Student, student_id) is None:
        raise HTTPException(404, "Student not found")
    if image.content_type not in {"image/jpeg", "image/png"}:
        raise HTTPException(415, "Only JPEG and PNG accepted")
    body = await image.read(5 * 1024 * 1024 + 1)
    if len(body) > 5 * 1024 * 1024:
        raise HTTPException(413, "Image too large")
    recognizer = FaceRecognitionAdapter()
    if recognizer.engine is None:
        raise HTTPException(503, recognizer.reason)
    try:
        validate_image(body)
        vector = await run_in_threadpool(recognizer.encode, body)
    except Exception:
        raise HTTPException(422, "Image must contain exactly one clear face")
    reference = db.get(FaceReference, student_id)
    if reference is None:
        reference = FaceReference(student_id=student_id, enrolled_by=username, embedding="")
        db.add(reference)
    from app.models.school import utcnow
    reference.embedding = json.dumps(vector.tolist())
    reference.consent_at = utcnow()
    reference.enrolled_by = username
    db.commit()
    return {"enrolled": True, "raw_image_stored": False}


@router.delete("/students/{student_id}/face", status_code=204)
def delete_face(student_id: int, _: str = Depends(verify_token), db: Session = Depends(get_db)):
    if db.get(Student, student_id) is None:
        raise HTTPException(404, "Student not found")
    reference = db.get(FaceReference, student_id)
    if reference:
        db.delete(reference)
        db.commit()
