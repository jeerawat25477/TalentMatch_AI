"""Pydantic v2 models สำหรับ request/response ของ API.

หมายเหตุ: โมเดลผลลัพธ์ของ LLM node (เช่น JobRequirement) อยู่ในเลเยอร์ agents/
ไฟล์นี้เก็บเฉพาะสัญญา (contract) ของ HTTP API เท่านั้น.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# ---------- Jobs ----------
# 'closed' = ปิดรับสมัคร (เช่น รับพนักงานได้แล้ว) ข้อมูลยังอยู่ครบ ไม่ใช่การลบ
JobStatus = Literal["open", "closed"]


class JobCreate(BaseModel):
    raw_text: str = Field(..., min_length=1, description="ข้อความ JD ดิบ")


class JobStatusUpdate(BaseModel):
    status: JobStatus = Field(..., description="'open' รับสมัครอยู่ | 'closed' ปิดรับ")


class JobOut(BaseModel):
    id: UUID
    title: str
    raw_text: str
    parsed_criteria: Optional[dict[str, Any]] = None
    status: JobStatus = "open"
    closed_at: Optional[datetime] = None
    created_at: datetime


class JobListItem(JobOut):
    """แถวในหน้าเลือกงาน — เพิ่มจำนวนผู้สมัครของแต่ละงาน."""
    candidate_count: int = 0


class JobDeleteOut(BaseModel):
    """ผลการลบถาวร — บอกจำนวนที่ถูกกวาดไปด้วย เพื่อให้ UI ยืนยันกับ HR ได้."""
    id: UUID
    deleted_candidates: int = 0
    deleted_threads: int = 0


# ---------- Candidates ----------
class CandidateSummary(BaseModel):
    """แถวในหน้ารายชื่อผู้สมัคร (เรียงตาม fit_score)."""
    id: UUID
    job_id: UUID
    full_name: str
    email: Optional[str] = None
    fit_score: Optional[int] = None
    audit_status: Optional[str] = None
    gap_analysis: Optional[dict[str, Any]] = None  # ใช้โชว์ชิปทักษะบนการ์ด
    created_at: datetime
    # ไม่มีผลวิเคราะห์ + ไม่มีใครกำลังรันให้ = ค้างถาวร ต้องกด "วิเคราะห์ใหม่" ถึงจะไปต่อ
    stalled: bool = False


class CandidateDeleteOut(BaseModel):
    """ผลการลบผู้สมัครถาวร (แถวใน evaluations/hr_decisions/เวกเตอร์ ถูก cascade ไปด้วย)."""
    id: UUID
    deleted_thread: bool = False


class CandidateDetail(CandidateSummary):
    raw_resume_text: Optional[str] = None
    parsed_resume: Optional[dict[str, Any]] = None
    gap_analysis: Optional[dict[str, Any]] = None
    audit_log: Optional[str] = None
    interview_plan: Optional[dict[str, Any]] = None
    email_draft: Optional[dict[str, Any]] = None
    email_sent_at: Optional[datetime] = None
    email_sent_to: Optional[str] = None
    email_send_count: int = 0  # จำนวนครั้งที่ส่งอีเมล (รวมส่งซ้ำ)
    # ผู้สมัครเก่าที่โปรไฟล์คล้ายกัน จาก retrieval agent (RAG) — ว่าง/None ถ้าปิด RAG
    similar_candidates: Optional[list[dict[str, Any]]] = None
    # สถานะกราฟ — ให้หน้าเว็บบอกได้ว่าการกดปุ่ม HR จะ "เดินต่อ" หรือ "ตัดสินใหม่ทับของเดิม"
    graph_status: Literal["awaiting_hr", "completed", "processing"] = "processing"
    # ถ้าผู้สมัครถูกรับเข้าเป็นพนักงานแล้ว = id ของระเบียนพนักงาน (ให้ UI ลิงก์ไปได้)
    employee_id: Optional[UUID] = None
    # คำตัดสินของ HR ที่บันทึกไว้ (ถ้ามี) — ให้ปุ่มโชว์สถานะที่ตัดสินไปแล้วหลังรีเฟรช
    hr_decision: Optional[Literal["approved", "rejected", "pending"]] = None


class CandidateSearchHit(BaseModel):
    """ผลค้นหาเชิงความหมายจากคลังเวกเตอร์ (ดู app/vectors.py)."""
    id: UUID
    full_name: str
    email: Optional[str] = None
    job_id: Optional[UUID] = None
    job_title: Optional[str] = None
    fit_score: Optional[int] = None
    distance: float = Field(..., description="cosine distance — ยิ่งน้อยยิ่งใกล้เคียง")


class ResumeUploadAccepted(BaseModel):
    job_id: UUID
    accepted: int = Field(..., description="จำนวนไฟล์ที่รับเข้าและสร้างแถวผู้สมัครแล้ว")
    candidate_ids: list[UUID]
    message: str = "กำลังประมวลผลเบื้องหลัง — โปรด poll รายชื่อผู้สมัครเพื่อดูผล"


# ---------- ส่งอีเมล ----------
class EmailSendIn(BaseModel):
    """ค่าที่ HR เห็น/แก้บนจอแล้วยืนยันส่ง — รับจาก request ไม่ดึงจาก DB ตรง.

    `to` เป็น EmailStr → pydantic validate รูปแบบให้ (กันส่งไปที่อยู่มั่ว)
    """
    to: EmailStr
    subject: str = Field(..., min_length=1, max_length=500)
    body: str = Field(..., min_length=1)


class EmailSendOut(BaseModel):
    candidate_id: UUID
    email_sent_to: str
    email_sent_at: datetime
    email_send_count: int = 0


# ---------- Auth ----------
class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    username: str


# ---------- Human-in-the-Loop ----------
class HRDecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]
    notes: Optional[str] = None


class HRDecisionOut(BaseModel):
    candidate_id: UUID
    decision: str
    notes: Optional[str] = None
    updated_at: datetime


# ---------- Employees (พนักงานที่รับเข้าหลังสัมภาษณ์ผ่าน) ----------
# probation ทดลองงาน | permanent ประจำ | terminated พ้นสภาพ | suspended พักงาน
EmployeeStatus = Literal["probation", "permanent", "terminated", "suspended"]


class EmployeeCreate(BaseModel):
    """ข้อมูลตอนกด 'รับเข้าเป็นพนักงาน' — position ว่างได้ (backend เติมด้วย job.title)."""
    position: Optional[str] = Field(None, max_length=255)
    department: Optional[str] = Field(None, max_length=255)
    salary: Optional[Decimal] = Field(None, ge=0)
    start_date: Optional[date] = None
    probation_end_date: Optional[date] = None
    hr_notes: Optional[str] = None


class EmployeeStatusUpdate(BaseModel):
    status: EmployeeStatus
    note: Optional[str] = Field(None, description="ต่อท้ายลง hr_notes พร้อม timestamp")


class EmployeeListItem(BaseModel):
    """แถวในหน้ารายชื่อพนักงาน."""
    id: UUID
    candidate_id: UUID
    full_name: str
    position: str
    department: Optional[str] = None
    status: EmployeeStatus
    start_date: Optional[date] = None
    hired_at: datetime


class EmployeeDetail(EmployeeListItem):
    job_id: Optional[UUID] = None
    job_title: Optional[str] = None            # join จาก jobs เพื่อลิงก์กลับ
    email: Optional[str] = None
    salary: Optional[Decimal] = None
    probation_end_date: Optional[date] = None
    hr_notes: Optional[str] = None
    updated_at: datetime
