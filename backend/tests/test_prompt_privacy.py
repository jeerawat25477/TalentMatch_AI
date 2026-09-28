"""ล็อกว่า AI ที่เขียนคำถามสัมภาษณ์และร่างอีเมล **ไม่เห็นข้อมูลส่วนตัว** ของผู้สมัคร.

ตัวเขียนคำถาม (planner) ได้แค่ชื่อตำแหน่ง ทักษะที่ผ่าน/ขาด และชื่อผู้สมัครเก่าที่คล้ายกัน
ตัวร่างอีเมล (drafter) ได้แค่ชื่อผู้สมัครกับชื่อตำแหน่ง · AI จึงไม่มีอายุ เพศ ศาสนา สถานภาพ
ให้เอาไปถามหรือเขียน — ระบบปลอดภัยด้วย "ไม่ส่งข้อมูลให้" ซึ่งแข็งแรงกว่าการตรวจทีหลัง

ถ้าเทสต์นี้ล้ม แปลว่ามีคนเพิ่มข้อมูลเรซูเม่เข้า prompt ความปลอดภัยข้อนี้หายไปแล้ว
**อย่าแก้เทสต์ให้ผ่าน** ถ้าต้องให้ AI เห็นเรซูเม่จริง (เช่นอยากให้ถามเจาะประสบการณ์) ให้ส่งเฉพาะส่วน
ที่เป็นงาน แล้วเพิ่มการตรวจคำถามที่ได้ก่อน — ไม่งั้น LLM เห็นเรซูเม่เต็มแล้วถามเรื่องครอบครัวได้ทันที
"""
import pytest

from app.agents.models import EmailDraft, InterviewPlan
from app.agents.nodes import drafter, planner

# ค่าที่ไม่มีทางอยู่ใน prompt โดยบังเอิญ — ค้นเจอแปลว่ารั่วจริง
PRIVATE = [
    "อายุ 47 ปี", "12/03/1979", "เพศทางเลือก", "ศาสนาซิกข์", "หย่าร้าง",
    "มีบุตร 3 คน", "สัญชาติลาว", "ซอยทดสอบลับ 99", "ส่วนสูง 158", "โรคประจำตัวทดสอบ",
]
RAW = "เรซูเม่\n" + "\n".join(PRIVATE) + "\nทักษะ: Python, Docker"


def _state(decision=None, score=80):
    return {
        "raw_jd": "Backend Developer\nPython",
        "raw_resumes": [{"candidate_id": "c1", "filename": "", "content": RAW}],
        "analyzed_jd": {"job_title": "Backend Developer", "required_skills": ["Python"],
                        "preferred_skills": ["Docker"]},
        "parsed_resumes": [{
            "candidate_id": "c1", "full_name": "สมใจ ทดสอบ", "skills": ["Python", "Docker"],
            "age": "อายุ 47 ปี", "birth_date": "12/03/1979", "gender": "เพศทางเลือก",
            "religion": "ศาสนาซิกข์", "marital_status": "หย่าร้าง", "children": "มีบุตร 3 คน",
            "nationality": "สัญชาติลาว", "address": "ซอยทดสอบลับ 99", "height": "ส่วนสูง 158",
            "health": "โรคประจำตัวทดสอบ", "raw_text": RAW,
        }],
        "evaluations": [{
            "candidate_id": "c1", "fit_score": score,
            "gaps": {"matched_required": ["Python"], "missing_required": [],
                     "matched_preferred": ["Docker"], "missing_preferred": []},
        }],
        "hr_decision": {"c1": decision} if decision else {},
        "hr_notes": {}, "interview_plans": {}, "email_drafts": {},
        "similar_candidates": {}, "bias_revision_count": {},
        "bias_revision_pending": {}, "bias_exclusions": {},
    }


@pytest.fixture
def prompts(monkeypatch):
    seen: list[str] = []

    def fake_plan(prompt, schema, **kw):
        seen.append(prompt)
        return InterviewPlan(questions=[])

    def fake_draft(prompt, schema, **kw):
        seen.append(prompt)
        return EmailDraft(kind="invitation", subject="s", body="b")

    monkeypatch.setattr(planner, "structured_invoke", fake_plan)
    monkeypatch.setattr(drafter, "structured_invoke", fake_draft)
    return seen


def _assert_clean(prompt: str, who: str):
    leaked = [p for p in PRIVATE if p in prompt]
    assert not leaked, (
        f"{who} ได้รับข้อมูลส่วนตัว {leaked} — AI จะเอาไปเขียนคำถาม/อีเมลที่เลือกปฏิบัติได้ "
        "ดู docstring ของไฟล์นี้ก่อนแก้"
    )


def test_ตัวเขียนคำถามไม่เห็นข้อมูลส่วนตัว(prompts):
    planner.plan_interviews(_state())
    assert len(prompts) == 1
    _assert_clean(prompts[0], "interview_planner")


@pytest.mark.parametrize("decision, score", [(None, 80), ("approved", 30), ("rejected", 80), (None, 20)])
def test_ตัวร่างอีเมลไม่เห็นข้อมูลส่วนตัว(prompts, decision, score):
    drafter.draft_emails(_state(decision, score))
    assert len(prompts) == 1
    _assert_clean(prompts[0], "email_drafter")
    # ชื่อผู้สมัครได้ — ต้องใช้ขึ้นต้นจดหมาย
    assert "สมใจ ทดสอบ" in prompts[0]
