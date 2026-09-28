"""สคริปต์แตกถ้อยคำอคติที่ถูกรวมเป็นก้อนเดียวในตำแหน่งเดิม — ไม่ต่อ DB ไม่เรียก LLM."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from resplit_jd_criteria import resplit  # noqa: E402

JD = "UI/UX Designer\nเพศหญิง อายุไม่เกิน 35 ปี"
COMBINED = {
    "status": "flagged",
    "log": "พบเกณฑ์อคติเรื่องเพศและอายุ\n⚠ เกณฑ์ใน JD ที่อาจมีอคติ (ไม่ได้ถูกใช้คิดคะแนน — ควรแก้ประกาศ): เพศหญิง อายุไม่เกิน 35 ปี",
    "jd_criteria": ["เพศหญิง อายุไม่เกิน 35 ปี"],
    "biased_required_skills": [], "biased_preferred_skills": [], "llm_checked": True,
}


def test_แตกก้อนรวมเป็นทีละเรื่อง():
    out = resplit(COMBINED, JD)
    assert out["jd_criteria"] == ["เพศหญิง", "อายุไม่เกิน 35 ปี"]
    assert out["log"].startswith("พบเกณฑ์อคติเรื่องเพศและอายุ\n⚠")
    assert out["log"].endswith("เพศหญิง, อายุไม่เกิน 35 ปี")
    assert out["log"].count("⚠") == 1
    # ช่องอื่นคงเดิม
    assert out["status"] == "flagged" and out["llm_checked"] is True


def test_แตกแล้วเป็นแบบเดียวกันไม่ต้องเปลี่ยน():
    assert resplit(resplit(COMBINED, JD), JD) is None


def test_ตำแหน่งที่ไม่มีอะไรต้องแตกไม่ถูกแตะ():
    clean = {**COMBINED, "status": "passed", "log": "ไม่พบ", "jd_criteria": []}
    assert resplit(clean, "Python Developer") is None


def test_ไม่มีผลตรวจ():
    assert resplit(None, JD) is None
