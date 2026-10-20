"""ล็อกว่าคำที่ LLM ใช้แทน "ไม่ได้ระบุ" ไม่หลุดไปเป็นข้อความบนหน้าเว็บ.

เจอจริง 2026-10-20: ประกาศที่ไม่มีวุฒิการศึกษา ได้ education เป็นสตริง "null" (ไม่ใช่ JSON null)
หน้ายืนยันเกณฑ์ใช้ `d?.education ?? ""` จึงโชว์คำว่า null ในช่อง "การศึกษา" ตรง ๆ
แก้ที่ model (validator) จุดเดียว — ผลจาก LLM, ป้ายที่เก็บไว้ใน jobs.jd_extraction และ
parsed_criteria เก่าที่โหลดกลับมาจึงผ่านกฎเดียวกันหมด ไม่ต้องจำแก้ทีละ caller
ไม่เรียก LLM จริง
"""
import pytest

from app.agents.models import JDExtraction, JDSkillItem, JobRequirement, ResumeProfile, blank_if_unstated
from app.agents.nodes.jd_analyzer import to_requirement

UNSTATED = ["null", "NULL", " null ", "None", "none", "N/A", "-", "—", "ไม่ระบุ", "ไม่มี", "", "   ", None]


@pytest.mark.parametrize("value", UNSTATED)
def test_unstated_becomes_blank(value):
    assert blank_if_unstated(value) == ""


@pytest.mark.parametrize("value", ["ปริญญาตรี", "B.Sc. Computer Science", "ป.ตรี สาขาคอมพิวเตอร์", "Nullable Inc."])
def test_real_education_is_kept(value):
    # "Nullable Inc." — ต้องเทียบทั้งคำ ไม่ใช่ขึ้นต้นด้วย null
    assert blank_if_unstated(f"  {value} ") == value


@pytest.mark.parametrize("value", UNSTATED)
def test_llm_null_never_reaches_requirement(value):
    """เส้นทางจริงของ /jobs/analyze: JDExtraction จาก LLM -> to_requirement -> JobRequirement."""
    ex = JDExtraction(
        job_title="Backend Developer", min_experience_years=2, education=value,
        items=[JDSkillItem(source_line="Python", name="Python", kind="technology",
                           necessity="must", section="qualifications")],
    )
    req = to_requirement(ex)
    assert req.education == ""
    assert req.model_dump()["education"] == ""


def test_old_parsed_criteria_with_null_loads_blank():
    """parsed_criteria ที่บันทึกไว้ก่อนแก้ อาจเก็บ "null" ไว้แล้ว — โหลดกลับต้องได้ค่าว่าง."""
    stored = {"job_title": "X", "min_experience_years": 0, "required_skills": [], "preferred_skills": [],
              "education": "null"}
    assert JobRequirement.model_validate(stored).education == ""


def test_resume_profile_null_education_is_blank():
    """ฝั่งเรซูเม่ใช้ LLM แบบเดียวกัน — หน้าผู้สมัครต้องไม่โชว์ null ในช่องการศึกษาเช่นกัน."""
    assert ResumeProfile(full_name="Suda", education="null").education == ""
