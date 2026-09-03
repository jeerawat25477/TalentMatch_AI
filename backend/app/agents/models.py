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


class JDBiasFlag(BaseModel):
    """ถ้อยคำหนึ่งจุดในประกาศที่อาจกีดกันผู้สมัครโดยไม่จำเป็น."""
    phrase: str = Field(..., description="ข้อความที่ยกมาจากประกาศตรง ๆ")
    reason: str = Field(..., description="ทำไมถ้อยคำนี้ถึงเป็นปัญหา")
    suggestion: str = Field(..., description="ควรแก้เป็นอะไรแทน")


class JDMustHaveReview(BaseModel):
    """ทักษะที่ประกาศระบุว่า 'ต้องมี' แต่ควรทบทวนว่าจำเป็นขนาดนั้นจริงไหม."""
    skill: str = Field(..., description="ชื่อทักษะตามที่เขียนในประกาศ")
    reason: str = Field(
        ...,
        description=(
            "เหตุผลที่ควรทบทวน เช่น น่าจะเป็น 'มีก็ดี' มากกว่า 'ต้องมี' "
            "หรือเข้มเกินระดับตำแหน่งจนตัดผู้สมัครที่ทำงานได้จริงทิ้ง"
        ),
    )


class JDReview(BaseModel):
    """ผลจาก JD Reviewer — คำแนะนำก่อนโพสต์ประกาศ (ไม่ใช่โหนดในกราฟหลัก).

    คนละจังหวะกับ JobRequirement: ตัวนั้น *สกัด* เกณฑ์ไปใช้ให้คะแนนผู้สมัคร
    ส่วนตัวนี้ *วิจารณ์ตัวประกาศเอง* ตั้งแต่ก่อนมีผู้สมัครสักคน
    """
    scope_assessment: Literal["too_broad", "balanced", "too_narrow"] = "balanced"
    scope_comment: str = Field(
        "", description="อธิบายสั้น ๆ ว่าทำไมถึงประเมินขอบเขตแบบนั้น"
    )
    bias_flags: list[JDBiasFlag] = Field(
        default_factory=list, description="ถ้อยคำที่อาจกีดกันผู้สมัครโดยไม่จำเป็น"
    )
    must_have_review: list[JDMustHaveReview] = Field(
        default_factory=list, description="ทักษะที่ระบุว่าต้องมีแต่ควรทบทวน"
    )
    missing_info: list[str] = Field(
        default_factory=list,
        description=(
            "ข้อมูลที่ประกาศรับสมัครควรมีแต่ยังขาด เช่น ช่วงเงินเดือน สถานที่ทำงาน "
            "รูปแบบการทำงาน ขอบเขตความรับผิดชอบ"
        ),
    )
    overall_comment: str = Field("", description="สรุปภาพรวมให้ HR อ่านเป็นย่อหน้าเดียว")


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
