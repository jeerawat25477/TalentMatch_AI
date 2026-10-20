"""Pydantic v2 models สำหรับ structured output ของแต่ละโหนด LLM."""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# คำที่ LLM ใช้แทน "ไม่ได้ระบุ" ในช่องข้อความ — เจอจริง 2026-10-20: ประกาศที่ไม่มีวุฒิการศึกษา
# ได้ education เป็นสตริง "null" (ไม่ใช่ JSON null) แล้วหน้ายืนยันเกณฑ์โชว์คำว่า null ในช่อง
_EMPTY_WORDS = {"null", "none", "nil", "n/a", "na", "-", "—", "ไม่ระบุ", "ไม่มี", "ไม่ได้ระบุ"}


def blank_if_unstated(value: object) -> str:
    """ค่าที่หมายถึง "ไม่ได้ระบุ" ให้เป็นสตริงว่าง ส่วนค่าจริงคืนตามเดิม (ตัดช่องว่างหัวท้าย)."""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in _EMPTY_WORDS else text


def email_or_none(value: object) -> Optional[str]:
    """อีเมลที่ใช้ได้ หรือ None — คำว่า "null"/"ไม่ระบุ" และข้อความที่ไม่มี @ ถือว่าไม่มีอีเมล.

    สำคัญกว่าแค่ช่องผู้รับ: candidates.same_person เทียบอีเมลเพื่อบอกว่า "คนละไฟล์แต่คนเดียวกัน"
    ถ้า LLM ตอบ "null" ให้เรซูเม่ 2 ใบที่ไม่มีอีเมล คนสองคนจะถูกจับเป็นคนเดียวกัน (2026-10-21)
    """
    text = blank_if_unstated(value)
    return text if "@" in text else None


class JobRequirement(BaseModel):
    """ผลจาก JD Analyzer — รูปแบบกลางที่ resume ก็ต้อง map เข้าหาได้."""
    job_title: str = Field(..., description="ชื่อตำแหน่ง")
    min_experience_years: int = Field(0, description="จำนวนปีขั้นต่ำ")
    required_skills: list[str] = Field(default_factory=list, description="ทักษะที่ต้องมี (Must-have)")
    preferred_skills: list[str] = Field(default_factory=list, description="ทักษะที่มีก็ดี (Nice-to-have)")
    education: str = Field("", description="ระดับการศึกษาที่ต้องการ")

    _blank_education = field_validator("education", mode="before")(blank_if_unstated)


class JDSkillItem(BaseModel):
    """ทักษะหนึ่งคำที่ jd_analyzer เจอในประกาศ พร้อมป้าย — **ไม่ได้ตัดสินฝั่งเอง**.

    เคยให้ LLM ใส่ required/preferred ตรง ๆ ตามกติกายาว ๆ ใน prompt แล้ววัดกับ
    gemini-2.5-flash-lite จริง (2026-09-19): "A, B หรือ C" ยังเป็นข้อบังคับทุกตัว หน้าที่งานยังหลุด
    และ "จะพิจารณาเป็นพิเศษ" ที่เคยถูกกลับกลายเป็นข้อบังคับ — จึงให้มันตอบคำถามแคบ ๆ ต่อคำแทน
    แล้วให้ jd_analyzer.to_requirement จัดฝั่งด้วยโค้ดที่เทสได้

    **ลำดับฟิลด์มีความหมาย:** โมเดลตอบตามลำดับ source_line จึงมาก่อนป้าย เพื่อให้มันเห็นคำว่า
    "or" / "such as" / "is a plus" ในบรรทัดนั้นก่อนจะตัดสิน
    """
    source_line: str = Field(..., description="ข้อความในประกาศที่คำนี้มา ยกมาตรง ๆ ไม่เกินหนึ่งบรรทัด")
    name: str = Field(..., description="ชื่อทางการของทักษะ/เทคโนโลยี เช่น 'PostgreSQL' — คำเดียว ห้ามรวมหลายตัว")
    kind: Literal[
        "technology", "method", "knowledge_field", "duty", "category", "role", "personal", "education"
    ] = Field(..., description="ชนิดของคำ")
    necessity: Literal["must", "one_of", "example", "plus"] = Field(
        ..., description="ประกาศบอกว่าคำนี้จำเป็นแค่ไหน"
    )
    section: Literal["duties", "qualifications", "unsectioned"] = Field(
        ..., description="คำนี้อยู่ในส่วนไหนของประกาศ"
    )
    group: str = Field(
        "", description="ชื่อกลุ่มของตัวเลือกที่มาด้วยกัน (เช่น 'cloud') เฉพาะ one_of/example · อื่น ๆ เว้นว่าง"
    )


class JDExtraction(BaseModel):
    """ผลดิบจาก jd_analyzer — แปลงเป็น JobRequirement ด้วย jd_analyzer.to_requirement."""
    job_title: str = Field(..., description="ชื่อตำแหน่ง")
    min_experience_years: int = Field(0, description="จำนวนปีขั้นต่ำ (ไม่ระบุ = 0)")
    education: str = Field("", description="ระดับการศึกษาและสาขาที่ต้องการ")
    items: list[JDSkillItem] = Field(default_factory=list, description="ทุกคำที่อาจเป็นทักษะในประกาศ")

    _blank_education = field_validator("education", mode="before")(blank_if_unstated)


class ResumeProfile(BaseModel):
    """ผลจาก Resume Parser — ฟอร์แมตเดียวกับ JD เพื่อทำ gap analysis แบบ field-by-field."""
    full_name: str = Field(..., description="ชื่อ-นามสกุลผู้สมัคร")
    email: Optional[str] = Field(None, description="อีเมล")
    total_experience_years: float = Field(0, description="ปีประสบการณ์รวม")
    skills: list[str] = Field(default_factory=list, description="ทักษะทั้งหมดของผู้สมัคร")
    education: str = Field("", description="วุฒิการศึกษาสูงสุด")

    _blank_education = field_validator("education", mode="before")(blank_if_unstated)
    _usable_email = field_validator("email", mode="before")(email_or_none)


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


class JDScreeningIssue(BaseModel):
    """ถ้อยคำหนึ่งจุดในประกาศที่ทำให้คัดกรองจากเรซูเม่ได้ไม่ดี พร้อมวิธีแก้."""
    phrase: str = Field(..., description="ข้อความที่ยกมาจากประกาศตรง ๆ")
    suggestion: str = Field(..., description="ควรเขียนใหม่เป็นอะไร หรือย้ายไปถามตอนสัมภาษณ์")


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
    """ผลจาก JD Reviewer — ประกาศนี้ใช้ **คัดกรองเรซูเม่** ได้ดีแค่ไหน (ไม่ใช่โหนดในกราฟหลัก).

    เดิมถามว่า "พร้อมโพสต์ไหม" แล้วแนะนำให้เพิ่มสถานที่ทำงาน/รูปแบบไฮบริด ซึ่งไม่มีผลกับคะแนน
    ผู้สมัครเลย ในระบบนี้ประกาศถูกใช้สกัดเกณฑ์คัดกรอง จึงตรวจสิ่งที่ทำให้คัดกรองพลาด
    ส่วนเรื่องอคติตัดออก — ตัวตรวจตอนกด "วิเคราะห์" (bias_auditor.audit_jd + กฎตายตัว) ทำอยู่แล้ว
    และแม่นกว่า ถ้ามีสองที่ HR จะเห็นผลสองชุดที่พูดไม่ตรงกัน
    """
    scope_assessment: Literal["too_broad", "balanced", "too_narrow"] = "balanced"
    scope_comment: str = Field(
        "", description="อธิบายสั้น ๆ ว่าทำไมถึงประเมินขอบเขตแบบนั้น"
    )
    unmeasurable: list[JDScreeningIssue] = Field(
        default_factory=list,
        description="เกณฑ์ที่วัดจากเรซูเม่ไม่ได้ เช่น ขยัน อดทน มีใจรักบริการ",
    )
    vague_skills: list[JDScreeningIssue] = Field(
        default_factory=list,
        description="ทักษะที่กว้างเกินจนจับคู่กับเรซูเม่ไม่ได้ เช่น เก่งคอมพิวเตอร์",
    )
    structure_issues: list[str] = Field(
        default_factory=list,
        description="โครงสร้างที่ทำให้ระบบแยกต้องมี/อยากได้ หรือตัวเลือก 'อย่างใดอย่างหนึ่ง' ผิด",
    )
    must_have_review: list[JDMustHaveReview] = Field(
        default_factory=list, description="ทักษะที่ระบุว่าต้องมีแต่ควรทบทวน"
    )
    posting_tips: list[str] = Field(
        default_factory=list,
        description=(
            "เฉพาะกรณีจะนำประกาศไปโพสต์ภายนอก (JobsDB ฯลฯ) — ข้อมูลที่ผู้สมัครอยากรู้แต่ยังขาด "
            "เช่น ช่วงเงินเดือน สถานที่ทำงาน · ไม่มีผลกับการคัดกรอง"
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
            "เกณฑ์อคติที่พบใน JD ดิบซึ่ง 'ไม่ใช่ทักษะ' (เพศ อายุ เชื้อชาติ/สัญชาติ ศาสนา สถาบันการศึกษา "
            "สถานภาพสมรส รูปลักษณ์ ความพิการ) ยกข้อความจากประกาศจริง "
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
