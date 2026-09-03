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
    # สองฟิลด์นี้ให้หน้ารายชื่อรู้ว่าใคร "รอ HR ตัดสิน" จริง ๆ (ใช้เปิด/ปิดติ๊กเลือกของ bulk)
    # เดิมมีแต่บน CandidateDetail ทำให้ dashboard เดาจากคะแนนอย่างเดียว ซึ่งแยกไม่ออกว่า
    # คนคะแนน 50-70 นั้นตัดสินไปแล้วหรือยัง
    graph_status: Literal["awaiting_hr", "completed", "processing"] = "processing"
    hr_decision: Optional[Literal["approved", "rejected", "pending"]] = None


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
    # ร่องรอยลูป critique/revise: auditor ถอดเกณฑ์ที่มีอคติแล้ว matcher คำนวณใหม่
    # {round, score_before, score_after, excluded_required, excluded_preferred, reason}
    bias_revision: Optional[dict[str, Any]] = None
    # หลักฐานจากเรซูเม่ของทักษะที่ตรงเกณฑ์ {ชื่อทักษะแบบที่สะกดใน JD: ข้อความที่ยกมา}
    # ตรวจกับข้อความเรซูเม่จริงแล้ว (agents/evidence.py) — None = แถวเก่าก่อนมีฟีเจอร์นี้
    skill_evidence: Optional[dict[str, str]] = None
    # ประโยคอธิบายที่มาของคะแนน (template ไม่ใช่ LLM) — None = แถวเก่าก่อนมีฟีเจอร์นี้
    score_explanation: Optional[str] = None
    # ความมั่นใจของผลวิเคราะห์ — คนละมิติกับ fit_score (ดู agents/bands.py)
    confidence: Optional[Literal["high", "medium", "low"]] = None
    # graph_status / hr_decision สืบทอดมาจาก CandidateSummary แล้ว (ประกาศซ้ำจะกลายเป็น
    # สองแหล่งที่หลุดไม่ตรงกันภายหลัง)
    # ถ้าผู้สมัครถูกรับเข้าเป็นพนักงานแล้ว = id ของระเบียนพนักงาน (ให้ UI ลิงก์ไปได้)
    employee_id: Optional[UUID] = None
    # เหตุผลที่ HR บันทึกไว้ตอนตัดสิน + เวลาที่บันทึกล่าสุด
    # ⚠️ hr_decisions.candidate_id เป็น UNIQUE และ hr.py upsert ทับแถวเดิม จึงเป็น
    # "คำตัดสินล่าสุด" ไม่ใช่ประวัติย้อนหลัง (updated_at คือคอลัมน์เวลาเดียวที่ตารางมี)
    hr_notes: Optional[str] = None
    hr_decided_at: Optional[datetime] = None


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
    # ไฟล์ที่ไม่ได้สร้างผู้สมัคร = ซ้ำ + อ่านข้อความไม่ออก (ทุกฟิลด์มี default ให้ client เก่าไม่พัง)
    skipped: int = 0
    # เคยอัปโหลดเข้าตำแหน่งงานนี้แล้ว (ตัดสินด้วย sha256 ของไบต์ไฟล์)
    duplicate_files: list[str] = []
    # สกัดข้อความไม่ได้/สั้นผิดปกติ — มักเป็นเรซูเม่สแกนหรือถ่ายรูปที่ไม่มีชั้นข้อความ
    unreadable_files: list[str] = []
    message: str = "กำลังประมวลผลเบื้องหลัง — โปรด poll รายชื่อผู้สมัครเพื่อดูผล"


# ---------- ส่งอีเมล ----------
# ต้องตรงกับ EmailDraft.kind ใน agents/models.py และ CHECK ในตาราง email_templates
EmailKind = Literal["invitation", "rejection"]


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


# ---------- เทมเพลตอีเมลที่บันทึกไว้ใช้ซ้ำ ----------
class EmailTemplateIn(BaseModel):
    """เทมเพลตที่ HR บันทึกไว้เอง — เป็นแค่ร่างตั้งต้น ไม่ใช่คำสั่งส่ง.

    ค่าที่ส่งจริงยังมาจาก EmailSendIn ที่ HR เห็นและยืนยันบนจอเสมอ
    (ดู CLAUDE.md "Email send is synchronous and HR-gated")
    """
    name: str = Field(..., min_length=1, max_length=255)
    kind: EmailKind
    subject_template: str = Field(..., min_length=1, max_length=500)
    body_template: str = Field(..., min_length=1)


class EmailTemplateOut(EmailTemplateIn):
    id: UUID
    created_at: datetime


class EmailTemplateDeleteOut(BaseModel):
    id: UUID


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


# ---------- ตัดสินหลายคนพร้อมกัน (bulk) ----------
class BulkDecisionIn(BaseModel):
    """ตัดสินหลายคนด้วยผลเดียวกัน — แต่ละคนยังเดินกราฟของตัวเองแยกกัน.

    (thread_id = candidate_id ตาม CLAUDE.md จึงรวมเป็นการรันเดียวไม่ได้จริง)
    """
    candidate_ids: list[UUID] = Field(..., min_length=1)
    decision: Literal["approved", "rejected"]
    notes: Optional[str] = None


class BulkDecisionSkip(BaseModel):
    id: UUID
    reason: str


class BulkDecisionAccepted(BaseModel):
    """ผลการ "รับเข้าคิว" ไม่ใช่ผลการตัดสิน — งานจริงรันเบื้องหลัง.

    ผลรายคนดูได้จาก GET /jobs/{id}/candidates ที่หน้าเว็บ poll อยู่แล้วทุก 4 วิ
    (graph_status จะเปลี่ยนเป็น completed เมื่อเดินกราฟจบ)
    ทุกฟิลด์มี default ตามแพตเทิร์น ResumeUploadAccepted เพื่อให้ client เก่าไม่พัง
    """
    accepted: int = 0
    candidate_ids: list[UUID] = []
    skipped: list[BulkDecisionSkip] = []
    message: str = "รับเข้าคิวแล้ว — ผลจะทยอยขึ้นในหน้ารายชื่อผู้สมัคร"


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
