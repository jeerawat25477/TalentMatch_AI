"""Pydantic v2 models สำหรับ structured output ของแต่ละโหนด LLM."""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class JobRequirement(BaseModel):
    """ผลจาก JD Analyzer — รูปแบบกลางที่ resume ก็ต้อง map เข้าหาได้."""
    job_title: str = Field(..., description="ชื่อตำแหน่ง")
    min_experience_years: int = Field(0, description="จำนวนปีขั้นต่ำ")
    required_skills: list[str] = Field(default_factory=list, description="ทักษะที่ต้องมี (Must-have)")
    preferred_skills: list[str] = Field(default_factory=list, description="ทักษะที่มีก็ดี (Nice-to-have)")
    education: str = Field("", description="ระดับการศึกษาที่ต้องการ")


class ResumeProfile(BaseModel):
    """ผลจาก Resume Parser — ฟอร์แมตเดียวกับ JD เพื่อทำ gap analysis แบบ field-by-field."""
    full_name: str = Field(..., description="ชื่อ-นามสกุลผู้สมัคร")
    email: Optional[str] = Field(None, description="อีเมล")
    total_experience_years: float = Field(0, description="ปีประสบการณ์รวม")
    skills: list[str] = Field(default_factory=list, description="ทักษะทั้งหมดของผู้สมัคร")
    education: str = Field("", description="วุฒิการศึกษาสูงสุด")


class SkillEvidence(BaseModel):
    """หลักฐานของแต่ละทักษะ — **แยก LLM call ออกจาก ResumeProfile โดยเจตนา**.

    เคยลองยัดเป็นฟิลด์หนึ่งใน ResumeProfile แล้ววัดกับเรซูเม่จริง: gemini-2.5-flash-lite
    เอาความสนใจไปอยู่กับการหาหลักฐานจนฟิลด์เดิมแย่ลงแบบวัดได้ (ชื่อ ปีประสบการณ์
    และวุฒิการศึกษาเพี้ยน — ดู memory-bank) การถามทีละงานจึงไม่ใช่การสิ้นเปลือง แต่จำเป็น
    """
    evidence: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "ชื่อทักษะ (สะกดตรงกับรายการที่ให้มาเป๊ะ) -> ข้อความสั้น ๆ ที่คัดลอกจากเรซูเม่ "
            "มาตรง ๆ เป็นที่มาว่าทำไมถึงนับว่าผู้สมัครมีทักษะนี้ ห้ามแต่งขึ้นเอง"
        ),
    )


class BiasAudit(BaseModel):
    """ผลจาก Bias Auditor."""
    is_biased: bool = Field(..., description="พบการใช้ข้อมูลอคติในการประเมินหรือไม่")
    audit_status: Literal["passed", "flagged"] = "passed"
    audit_log: str = Field("", description="สรุปสิ่งที่ตรวจพบ/แก้ไข")
    biased_required_skills: list[str] = Field(
        default_factory=list,
        description="required_skills ใน JD ที่ควรถอดออกก่อนคำนวณใหม่ เพราะเป็นเกณฑ์ที่อาจมีอคติ",
    )
    biased_preferred_skills: list[str] = Field(
        default_factory=list,
        description="preferred_skills ใน JD ที่ควรถอดออกก่อนคำนวณใหม่ เพราะเป็นเกณฑ์ที่อาจมีอคติ",
    )
    biased_jd_criteria: list[str] = Field(
        default_factory=list,
        description=(
            "เกณฑ์อคติที่พบใน JD ดิบซึ่ง 'ไม่ใช่ทักษะ' (เพศ อายุ เชื้อชาติ ศาสนา สถาบันการศึกษา) "
            "จึงถอดออกจากคะแนนไม่ได้ ต้องเตือน HR ให้แก้ประกาศแทน"
        ),
    )


class InterviewQuestion(BaseModel):
    """คำถามหนึ่งข้อ พร้อมเกณฑ์ให้ HR ใช้ประเมินคำตอบ."""
    question: str = Field(..., description="คำถามสัมภาษณ์")
    expected_answer: str = Field(
        ...,
        description=(
            "แนวคำตอบที่ดีควรครอบคลุมอะไรบ้าง — เขียนเป็นสาระสำคัญที่ต้องได้ยิน "
            "เพื่อให้ HR ที่ไม่ได้เชี่ยวชาญสายงานนี้ใช้ตัดสินได้ว่าคำตอบดีพอหรือไม่"
        ),
    )


class InterviewPlan(BaseModel):
    """ผลจาก Interview Planner."""
    questions: list[InterviewQuestion] = Field(
        default_factory=list, description="คำถามสัมภาษณ์พร้อมแนวคำตอบ"
    )


class EmailDraft(BaseModel):
    """ผลจาก Email Drafter (ใช้ได้ทั้งเชิญสัมภาษณ์และปฏิเสธ)."""
    kind: Literal["invitation", "rejection"]
    subject: str
    body: str
