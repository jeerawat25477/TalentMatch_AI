"""Pydantic v2 models สำหรับ request/response ของ API.

หมายเหตุ: โมเดลผลลัพธ์ของ LLM node (เช่น JobRequirement) อยู่ในเลเยอร์ agents/
ไฟล์นี้เก็บเฉพาะสัญญา (contract) ของ HTTP API เท่านั้น.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Optional
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, EmailStr, Field, computed_field


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
    # เกณฑ์ที่ AI ดึงไว้ตอนสร้างตำแหน่ง (เก็บตอน HR แก้ครั้งแรก) · None = ยังไม่เคยแก้
    ai_criteria: Optional[dict[str, Any]] = None
    # None = parsed_criteria ยังเป็นของ AI ล้วน
    criteria_edited_at: Optional[datetime] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def criteria_warnings(self) -> list[str]:
        """คำเตือนของเกณฑ์ปัจจุบัน (เช่น ไม่มีทักษะที่ต้องมีเลย) ให้การ์ดเกณฑ์แสดง.

        คำนวณจาก parsed_criteria ทุกครั้ง ใช้ฟังก์ชันเดียวกับหน้าจอแก้เกณฑ์ จึงไม่มีกติกาชุดที่สอง
        และไม่ต้องเก็บลง DB · import ในฟังก์ชันเพื่อไม่ให้ schemas ลากเลเยอร์ agents เข้ามาตอนโหลด
        """
        if not self.parsed_criteria:
            return []
        from app.criteria_edit import criteria_warnings

        return criteria_warnings(
            list(self.parsed_criteria.get("required_skills") or []),
            list(self.parsed_criteria.get("preferred_skills") or []),
        )


# ---------- HR แก้เกณฑ์ทักษะ (app/criteria_edit.py) ----------
SkillName = Annotated[str, Field(max_length=100)]


class CriteriaIn(BaseModel):
    """รายการทักษะที่ HR แก้แล้ว — ทำความสะอาดต่อที่ criteria_edit.normalize_criteria."""
    required_skills: list[SkillName] = Field(default_factory=list, max_length=50)
    preferred_skills: list[SkillName] = Field(default_factory=list, max_length=50)


class CriteriaImpact(BaseModel):
    """ผลต่อผู้สมัครหนึ่งคน — คะแนนเดิมกับใหม่ คำนวณด้วย matcher.evaluate_skills ตัวเดียวกับกราฟ."""
    candidate_id: UUID
    full_name: str
    old_score: int
    new_score: int
    old_band: Literal["pass", "review", "fail"]
    new_band: Literal["pass", "review", "fail"]
    hr_decision: Optional[Literal["approved", "rejected", "pending"]] = None
    email_sent: bool = False


class CriteriaPreviewOut(BaseModel):
    required_skills: list[str]
    preferred_skills: list[str]
    # คำที่ไม่ใช่ทักษะ (เช่นชื่อบทบาท) ซึ่งถูกคัดออก — แจ้ง HR ไม่ทิ้งเงียบ
    dropped: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    impact: list[CriteriaImpact] = Field(default_factory=list)


class CriteriaSaveOut(CriteriaPreviewOut):
    job: JobOut


class JobListItem(JobOut):
    """แถวในหน้าเลือกงาน — เพิ่มจำนวนผู้สมัครของแต่ละงาน."""
    candidate_count: int = 0


class JobDeleteOut(BaseModel):
    """ผลการลบถาวร — บอกจำนวนที่ถูกกวาดไปด้วย เพื่อให้ UI ยืนยันกับ HR ได้."""
    id: UUID
    deleted_candidates: int = 0
    deleted_threads: int = 0


class JDReviewIn(BaseModel):
    """ร่างประกาศที่ HR ขอให้ตรวจก่อนโพสต์ — ยังไม่มี job_id เพราะยังไม่ได้สร้างงาน.

    จำกัดความยาวไว้ที่ชั้น schema เพื่อให้ประกาศที่ยาวผิดปกติถูกปฏิเสธ (422)
    ตั้งแต่ก่อนเสียโควตา LLM
    """
    raw_text: str = Field(..., min_length=1, max_length=20000)


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
    # "interrupted" = ค้างกลางทาง (ตัดสินแล้วแต่ไม่เดินต่อ / auto-advance ล้ม) ดู runner.resolve_graph_status
    graph_status: Literal["awaiting_hr", "completed", "processing", "interrupted"] = "processing"
    hr_decision: Optional[Literal["approved", "rejected", "pending"]] = None
    # สถานะในคิวประมวลผล (None = ไม่มีงานค้าง) — แยกจาก stalled โดยตั้งใจ:
    # "รอคิว" กับ "เลื่อนเพราะโควตาเต็ม" คือระบบยังดูแลอยู่ ห้ามให้ HR เข้าใจว่าพัง
    queue_status: Optional[Literal["queued", "running", "deferred_quota"]] = None
    # คะแนนก่อนถูกคำนวณใหม่เพราะ HR แก้เกณฑ์ทักษะ (None = ไม่เคยถูกคำนวณใหม่)
    rescored_from: Optional[int] = None
    # แบนด์เปลี่ยนจากตอนที่กราฟ/HR ตัดสินไว้ และ HR ยังไม่ได้ตัดสินใหม่ — ดู criteria_edit.needs_recheck
    needs_recheck: bool = False


class CandidateDeleteOut(BaseModel):
    """ผลการลบผู้สมัครถาวร (แถวใน evaluations/hr_decisions/เวกเตอร์ ถูก cascade ไปด้วย)."""
    id: UUID
    deleted_thread: bool = False


# ---------- องค์ประกอบของ fit score ----------
# มาจาก agents/nodes/matcher.py::score_breakdown ที่เดียว (สูตรเดียวกับ compute_fit_score)
# หน้าเว็บแสดงผลตัวเลขเหล่านี้ตรง ๆ ห้ามคำนวณน้ำหนัก 60/40 เองฝั่ง frontend
class ScoreSide(BaseModel):
    matched: int
    total: int
    # น้ำหนักหลังเฉลี่ยใหม่ เป็นส่วนของ 100 (สองฝั่ง 60/40 · ฝั่งเดียว 100)
    weight: float
    points: float


class ScoreBreakdown(BaseModel):
    # None = JD ไม่ได้ระบุทักษะฝั่งนั้น (ไม่ใช่ 0/0 ที่ดูเหมือนเสียคะแนน)
    required: Optional[ScoreSide] = None
    preferred: Optional[ScoreSide] = None
    total: float
    # JD ไม่มีทักษะให้เทียบเลย → คะแนนถูกบังคับเป็นค่ากลาง ไม่ได้มาจากการเทียบ
    no_criteria: bool = False
    # False = คะแนนที่บันทึกไว้คำนวณด้วยสูตรเดิม (รวมแล้วไม่เท่า fit_score) ให้ UI เตือน
    matches_stored_score: bool = True


# ---------- ผลสัมภาษณ์จริง ----------
# ⚠️ คนละเรื่องกับ hr_decisions.decision: อันนั้นคือคำตัดสินคัดกรอง ("ให้ผ่านไปสัมภาษณ์ไหม")
# ที่กราฟอ่านไปเลือกเส้นทาง ส่วนอันนี้คือสิ่งที่เกิดขึ้นหลังสัมภาษณ์จริง ซึ่งกราฟไม่เคยเห็น
InterviewResult = Literal["pass", "fail", "standby"]


class QuestionScore(BaseModel):
    """คะแนนรายข้อ อ้างอิงคำถามจาก evaluations.interview_plan."""

    question: str = Field(..., max_length=2000)
    # 1-5 · ปล่อยว่างได้ = ไม่ได้ถามข้อนี้ ซึ่งต่างจากถามแล้วได้ 1 คะแนน
    # ช่วงนี้บังคับที่นี่ที่เดียว — CHECK ใน Postgres ตรวจค่าข้างใน JSONB array ไม่ได้
    score: Optional[int] = Field(None, ge=1, le=5)
    note: Optional[str] = Field(None, max_length=2000)


class InterviewOutcomeUpsert(BaseModel):
    result: InterviewResult
    question_scores: list[QuestionScore] = Field(default_factory=list)
    overall_note: Optional[str] = Field(None, max_length=5000)
    # วันที่สัมภาษณ์จริง ไม่ใช่วันที่กรอกฟอร์ม
    interviewed_at: Optional[date] = None


class InterviewOutcome(BaseModel):
    """รูปที่คืนกลับ — ใช้ทั้งใน response ของ PUT และฝังใน CandidateDetail."""

    result: InterviewResult
    question_scores: Optional[list[QuestionScore]] = None
    overall_note: Optional[str] = None
    interviewed_at: Optional[date] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------- ข้อเสนอจ้างงาน (ขั้น "ยื่นข้อเสนอ") ----------
OfferResponse = Literal["pending", "accepted", "declined"]


class JobOfferUpsert(BaseModel):
    """บันทึกหรือแก้ข้อเสนอ — HR กรอกเอง ไม่มี LLM เกี่ยว.

    ไม่ validate ว่า respond_by ต้องไม่อยู่ในอดีต: "วันนี้" ขึ้นกับโซนเวลาของผู้ใช้ซึ่ง backend
    ไม่รู้ และการบันทึกข้อเสนอย้อนหลังก็เป็นเรื่องปกติ
    """
    position: str = Field(..., min_length=1, max_length=255)
    # ข้อมูลอ่อนไหว — ห้ามเขียนลง log
    salary: Optional[Decimal] = Field(None, ge=0)
    start_date: Optional[date] = None
    respond_by: Optional[date] = None
    note: Optional[str] = Field(None, max_length=2000)


class JobOfferResponseIn(BaseModel):
    """คำตอบของผู้สมัครที่ HR บันทึก — ตอบรับ **ไม่ใช่การจ้าง** (การจ้างผ่านหน้าต่างรับเข้าเท่านั้น)."""
    response: Literal["accepted", "declined"]
    decline_reason: Optional[str] = Field(None, max_length=1000)


class JobOffer(BaseModel):
    """รูปที่คืนกลับ — ใช้ทั้งใน response ของ PUT/POST และฝังใน CandidateDetail."""
    position: str
    salary: Optional[Decimal] = None
    start_date: Optional[date] = None
    respond_by: Optional[date] = None
    note: Optional[str] = None
    response: OfferResponse = "pending"
    decline_reason: Optional[str] = None
    offered_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


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
    # ผลสัมภาษณ์จริงที่ HR กรอกเอง — None = ยังไม่เคยบันทึก (แถวเก่าทั้งหมดเป็นแบบนี้)
    # มาพร้อม CandidateDetail เลยเพื่อไม่ให้หน้า deep dive ต้องยิงอีกรอบ
    interview_outcome: Optional[InterviewOutcome] = None
    # ข้อเสนอจ้างงาน — None = ยังไม่เคยยื่น (หรือลากการ์ดไปขั้นยื่นข้อเสนอโดยไม่บันทึกรายละเอียด)
    # อยู่ต่อแม้ขั้นเปลี่ยนไปแล้ว ไทม์ไลน์จึงรู้ว่าเคยยื่นข้อเสนอ แม้ผู้สมัครปฏิเสธไปแล้ว
    offer: Optional[JobOffer] = None
    # ขั้นบนกระดานติดตาม คำนวณด้วย hiring_board.board_stage ตัวเดียวกับหน้ากระดาน
    # None = ไม่อยู่บนกระดาน (ยังไม่ผ่านคัดกรอง / ไม่ผ่าน / รอ HR)
    # forward ref: BoardStage ประกาศไว้ด้านล่าง — มี model_rebuild() ต่อท้ายไฟล์
    board_stage: Optional["BoardStage"] = None
    stage_moved_at: Optional[datetime] = None
    # นัดสัมภาษณ์จาก hiring_stage — None = ยังไม่ได้ตั้ง (หน้า deep dive ซ่อนบล็อกนัด)
    scheduled_at: Optional[datetime] = None
    location: Optional[str] = None
    # สองเวลานี้มีไว้ให้ไทม์ไลน์รายคนเรียงเหตุการณ์ได้ครบ — ค่าที่เก็บอยู่แล้วในตารางอื่น
    # ไม่ใช่ข้อมูลใหม่ · None = เหตุการณ์นั้นยังไม่เกิด (แถวเก่าที่ถูกปฏิเสธไปแล้วจะ
    # ไม่มีทั้งคู่) ฝั่งหน้าเว็บกรองจุดที่เป็น null ทิ้ง ไม่ใช่โชว์จุดว่าง
    # ร่างอีเมลฉบับที่ HR แก้เองและกดบันทึก {subject, body} — None = ยังไม่เคยแก้
    # คนละคอลัมน์กับ email_draft ของ AI โดยตั้งใจ: กราฟเดินรอบใหม่เขียนทับหรือล้าง
    # คอลัมน์นั้นได้ ถ้าเก็บร่างของ HR ไว้ที่นั่น งานที่พิมพ์เองจะหายโดยไม่มีใครรู้
    email_draft_edited: Optional[dict[str, Any]] = None
    email_draft_edited_at: Optional[datetime] = None
    evaluated_at: Optional[datetime] = None   # evaluations.created_at (AI ให้คะแนนเสร็จ)
    hired_at: Optional[datetime] = None       # employees.hired_at (employee_id มีอยู่แล้ว)
    # องค์ประกอบคะแนนทีละฝั่ง คำนวณตอนอ่านจาก gap_analysis (ไม่ได้เก็บลง DB)
    # None = ยังไม่มีผลวิเคราะห์ (gap_analysis เป็น null)
    score_breakdown: Optional[ScoreBreakdown] = None


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


class EmailDraftIn(BaseModel):
    """ร่างอีเมลฉบับที่ HR แก้เองแล้วกดบันทึก — เก็บไว้เฉย ๆ ไม่ได้ส่ง.

    ไม่มีฟิลด์ `to`: ผู้รับยังต้องยืนยันบนจอตอนกดส่งทุกครั้ง (ดู EmailSendIn) การเก็บ
    ผู้รับไว้ในร่างจะกลายเป็นค่าที่ค่อย ๆ เก่าแล้วถูกส่งโดยไม่มีใครอ่านซ้ำ
    """
    subject: str = Field(..., min_length=1, max_length=500)
    body: str = Field(..., min_length=1)
    # ร่างนี้เป็นอีเมลแบบไหนตอนที่ HR บันทึก — ไม่บังคับ (ร่างที่บันทึกก่อนมีฟิลด์นี้ไม่มีค่า)
    # มีไว้ให้หน้าเว็บเตือนได้ เมื่อโหมดของการ์ดเปลี่ยนไปแล้วแต่ร่างที่บันทึกไว้ยังเป็นอีกแบบ
    # เช่นบันทึกร่างปฏิเสธไว้ แล้ว HR ดึงผู้สมัครกลับเข้ากระบวนการ
    kind: Optional[EmailKind] = None


class EmailDraftOut(BaseModel):
    candidate_id: UUID
    subject: str
    body: str
    kind: Optional[EmailKind] = None
    edited_at: datetime


class EmailDraftDeleteOut(BaseModel):
    """ลบร่างของ HR แล้วกลับไปใช้ร่างของ AI (ร่างของ AI ไม่เคยถูกแตะ)."""
    candidate_id: UUID
    cleared: bool = True


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


# ---------- ค่าตั้งค่าระบบ ----------
class EmailIntakeSettingIn(BaseModel):
    """สวิตช์เปิด/ปิดปากทางรับอีเมล — มีแค่ฟิลด์เดียวโดยตั้งใจ.

    ⚠️ **ห้ามเพิ่มฟิลด์ IMAP host/user/password ที่นี่เด็ดขาด** ความลับต้องอยู่ใน env
    เท่านั้น ไม่วิ่งผ่าน request/response (ดู CLAUDE.md หัวข้อ Secrets)
    """
    enabled: bool


class EmailIntakeSettingOut(BaseModel):
    """สถานะปากทางรับอีเมลสำหรับหน้าตั้งค่า."""
    enabled: bool
    # บอกแค่ว่า "ตั้งค่า IMAP ครบไหม" ไม่คืนค่าจริงกลับไป — HR ต้องรู้ว่ากดเปิดแล้วจะ
    # ทำงานได้จริงไหม โดยไม่ต้องเห็นรหัสผ่าน
    imap_configured: bool
    last_poll_at: Optional[str] = None
    last_error: Optional[str] = None
    # นับจาก email_intake_log ของวันนี้ ไม่ใช่ตัวแปรในหน่วยความจำที่รีเซ็ตตอนรีสตาร์ต
    matched_count_today: int = 0
    unmatched_count_today: int = 0
    # รูปแบบที่อยู่รับสมัคร เช่น "recruit+{job_id}@company.com" — หน้าเว็บเติม job_id เอง
    # มาจาก IMAP_USER แหล่งเดียวกับที่ worker ใช้ดึงเมล เพื่อไม่ให้โชว์กล่องหนึ่งแต่ดึงอีกกล่อง
    # None = ยังไม่ได้ตั้ง IMAP_USER (หน้าเว็บซ่อนบล็อกนั้น) · ไม่ใช่ความลับ ต่างจากรหัสผ่าน
    apply_address_template: Optional[str] = None


IntakeOutcome = Literal[
    "matched", "unmatched", "duplicate", "unreadable", "no_attachment", "job_closed", "error"
]


class EmailIntakeActivityItem(BaseModel):
    """อีเมลหนึ่งฉบับ (หรือไฟล์แนบหนึ่งไฟล์) ที่ worker จัดการไปแล้ว — ป้อนฟีดและการแจ้งเตือน.

    ⚠️ ไม่มี uid/uid_validity — เป็นเคอร์เซอร์ภายในของ worker ไม่มีความหมายกับ HR
    """
    id: UUID
    outcome: IntakeOutcome
    from_addr: Optional[str] = None
    subject: Optional[str] = None
    detail: Optional[str] = None
    job_id: Optional[UUID] = None
    job_title: Optional[str] = None
    # null ได้แม้ outcome = matched: ผู้สมัครอาจถูกลบไปแล้ว (log ไม่มี FK โดยตั้งใจ)
    candidate_id: Optional[UUID] = None
    candidate_name: Optional[str] = None
    created_at: datetime


# ---------- กระดานติดตามผู้สมัคร ----------
# ค่าที่เก็บได้จริงในคอลัมน์ hiring_stage.stage (ตรงกับ CHECK ใน schema.sql)
HiringStage = Literal["invited", "scheduled", "interviewed", "offer", "declined"]

# ค่าที่ API คืน/รับ — มี "hired" เพิ่มเข้ามา แต่ **ไม่เคยถูกเก็บลงคอลัมน์**
# ขาออก: อนุมานจากการมีแถวใน employees
# ขาเข้า: ต้องรับไว้ให้ผ่าน validation ก่อน เพื่อจะได้ตอบ 400 พร้อมข้อความที่บอกทางออก
#         ถ้าใช้ HiringStage (ไม่มี hired) pydantic จะตัดตั้งแต่ validation แล้วตอบ 422
#         พร้อม error ดิบซึ่งไม่ได้บอก HR ว่าให้ไปใช้ปุ่มรับเข้าเป็นพนักงานแทน
BoardStage = Literal[
    "invited", "scheduled", "interviewed", "offer", "declined", "hired"
]

# CandidateDetail.board_stage อ้าง BoardStage ก่อนประกาศ — resolve ที่นี่ทันที
# ไม่ปล่อยให้ pydantic ไป resolve เองตอน validate ครั้งแรก (พังตอนรันจริงแทนตอน import)
CandidateDetail.model_rebuild()


class BoardItem(BaseModel):
    """การ์ดหนึ่งใบบนกระดานติดตามของตำแหน่งงานหนึ่ง."""
    candidate_id: UUID
    full_name: str
    fit_score: Optional[int] = None
    # ความมั่นใจของผลวิเคราะห์ — คนละมิติกับ fit_score (ดู agents/bands.py)
    confidence: Optional[Literal["high", "medium", "low"]] = None
    stage: BoardStage = "invited"
    # มีค่า = ถูกรับเข้าเป็นพนักงานแล้ว (stage จะเป็น 'hired' ไปด้วยเสมอ)
    employee_id: Optional[UUID] = None
    # การ์ดอยู่บนกระดานแต่ตอนนี้ไม่เข้าเกณฑ์แล้ว เช่น HR กลับคำทีหลัง — UI ขึ้นป้ายเตือน
    screening_conflict: bool = False
    # None = ยังไม่เคยย้ายขั้น (ไม่มีแถวใน hiring_stage) ไม่ใช่ "ย้ายตอนนี้"
    moved_at: Optional[datetime] = None
    # ให้ HR เห็นว่าเคยส่งอีเมลเชิญไปแล้วหรือยัง โดยไม่ต้องเปิดหน้ารายละเอียด
    email_sent_at: Optional[datetime] = None
    # ผลสัมภาษณ์ (ถ้าบันทึกไว้แล้ว) — ขึ้นเป็นป้ายบนการ์ดทุกคอลัมน์ ไม่ใช่เฉพาะ
    # "สัมภาษณ์แล้ว" เพราะพอย้ายไป "ยื่นข้อเสนอ" HR ก็ยังต้องเห็นว่าผลออกมายังไง
    interview_result: Optional[InterviewResult] = None
    # นัดสัมภาษณ์ — None = ยังไม่ได้ตั้ง
    scheduled_at: Optional[datetime] = None
    location: Optional[str] = None


class StageUpdate(BaseModel):
    """ย้ายการ์ดไปขั้นถัดไป (หรือย้อนกลับ — ไม่บังคับทิศทาง).

    `scheduled_at`/`location` เป็น **partial update**: ไม่ส่งฟิลด์มา = คงค่าเดิม ·
    ส่ง null มาตรง ๆ = ล้างค่า (ยกเลิกนัด) · router แยกสองกรณีนี้ด้วย model_fields_set
    ถ้าใช้ COALESCE แทน HR จะล้างวันนัดที่กรอกผิดไม่ได้เลย
    """
    stage: BoardStage
    note: Optional[str] = Field(None, max_length=2000)
    # AwareDatetime: ต้องมีโซนเวลาเสมอ เวลาแบบไม่มีโซนถูกปฏิเสธ (422) — ถ้ารับไว้ Postgres
    # จะตีความเป็น UTC แล้วนัดบ่ายสองโมงของ HR ในไทยจะกลายเป็นสามทุ่มในปฏิทินแบบเงียบ ๆ
    scheduled_at: Optional[AwareDatetime] = None
    # ข้อความอิสระ ไม่ validate รูปแบบ มีแค่เพดานความยาวกันข้อมูลขยะ
    location: Optional[str] = Field(None, max_length=500)


class FunnelStage(BaseModel):
    """หนึ่งขั้นของ funnel รวมผู้สมัครทั้งตำแหน่ง (GET /jobs/{id}/funnel).

    เป็นเซตซ้อนกันเสมอ: คนที่อยู่ขั้นหลังถูกนับรวมในทุกขั้นก่อนหน้าด้วย จำนวนจึง
    ลดหลั่นลงเท่านั้น ห้ามเพิ่มขึ้น (ดู routers/hiring_board.py::_funnel_flags)
    """
    label: str
    count: int


class InterviewSlot(BaseModel):
    """หนึ่งนัดสัมภาษณ์ในตารางรวมทุกตำแหน่ง (GET /interviews).

    อ่านจาก hiring_stage.scheduled_at ล้วน — ไม่มีตารางนัดแยก เพราะวันนัดเป็นสมบัติของ
    "ขั้นที่ผู้สมัครอยู่" ไม่ใช่ของกิจกรรมอิสระ (คนหนึ่งมีนัดที่ยังไม่ผ่านได้ครั้งเดียว)
    """
    candidate_id: UUID
    full_name: str
    job_id: UUID
    job_title: str
    scheduled_at: datetime
    location: Optional[str] = None
    stage: BoardStage
    # ผลสัมภาษณ์ถ้าบันทึกแล้ว — None = ยังไม่บันทึก
    interview_result: Optional[InterviewResult] = None
    # เลยเวลานัดมาแล้วแต่ยังไม่บันทึกผล — ให้ HR เห็นว่าอะไรค้างอยู่
    overdue: bool = False


InterviewSlot.model_rebuild()
