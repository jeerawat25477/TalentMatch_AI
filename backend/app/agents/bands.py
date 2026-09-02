"""เส้นแบ่งคะแนน (fit score band) — **แหล่งความจริงเดียว** ของทั้งระบบ.

เดิมเลข 50/70 ถูกเขียนซ้ำใน graph.py, runner.py, drafter.py, matcher.py,
scripts/recompute_scores.py และ frontend/lib/types.ts — แก้ทีต้องไล่ทุกจุด
ถ้าลืมจุดใดจุดหนึ่ง ป้ายสีในเว็บกับเส้นทางที่กราฟเดินจริงจะไม่ตรงกันแบบเงียบ ๆ

    fit > 70        → ผ่าน  : ไปสัมภาษณ์อัตโนมัติ (runner auto-resume)
    50 ≤ fit ≤ 70   → รอ HR : กราฟหยุดที่ interrupt_before=["interview_planner"]
    fit < 50        → ไม่ผ่าน: ไป email_drafter ร่างอีเมลปฏิเสธ

ฝั่ง frontend มีสำเนาอยู่ที่ frontend/lib/types.ts (scoreBand) — แก้ที่นี่แล้วต้องแก้ที่นั่นด้วย
"""
from typing import Literal

# คะแนน "มากกว่า" ค่านี้ = ผ่านอัตโนมัติ ไม่ต้องรอ HR
AUTO_ADVANCE_ABOVE = 70
# คะแนน "ตั้งแต่" ค่านี้ขึ้นไป = ยังไปต่อได้ (ต่ำกว่านี้คือปฏิเสธ)
REVIEW_FROM = 50

Band = Literal["pass", "review", "fail"]


def band(fit_score: int) -> Band:
    if fit_score > AUTO_ADVANCE_ABOVE:
        return "pass"
    if fit_score >= REVIEW_FROM:
        return "review"
    return "fail"


def should_auto_advance(fit_score: int) -> bool:
    """คะแนนสูงพอที่จะข้ามการรอ HR ได้เลยหรือไม่."""
    return band(fit_score) == "pass"


def is_rejected_by_score(fit_score: int) -> bool:
    """คะแนนต่ำจนควรร่างอีเมลปฏิเสธ (เมื่อ HR ยังไม่ได้ตัดสินสวน)."""
    return band(fit_score) == "fail"


# ---------- ความมั่นใจของผลวิเคราะห์ (คนละมิติกับ fit score) ----------
# fit score = "เหมาะกับงานแค่ไหน" · confidence = "ผลนี้อิงข้อมูลที่ครบถ้วนแค่ไหน"
# ผู้สมัครคะแนน 90 ที่ confidence ต่ำ แปลว่าอย่าเพิ่งเชื่อ 90 นั้น ให้เปิดไฟล์ดูเอง
#
# ⚠️ คำนวณจากสัญญาณที่วัดได้จริงเท่านั้น **ห้ามให้ LLM ประเมินความมั่นใจของตัวเอง** —
# self-rated confidence มั่นใจเกินจริงเป็นปกติ จึงไม่ได้บอกอะไรเลย

# ข้อความที่สกัดได้ (นับเฉพาะอักขระที่ไม่ใช่ช่องว่าง) ต่ำกว่านี้ = น่าสงสัย แม้จะผ่าน
# ด่านขั้นต่ำ MIN_RESUME_TEXT_CHARS (80) มาได้ก็ตาม
CONFIDENCE_TEXT_LOW = 400
# เทียบของจริง: เรซูเม่ไทยที่วัดไว้ 1,951 และ 2,870 ตัวอักษร sample อังกฤษสั้นสุด ~350
CONFIDENCE_TEXT_HIGH = 1200
# สัดส่วนทักษะที่ "ตรงเกณฑ์" และมีหลักฐานยืนยันได้ — หายืนยันไม่ได้เลยคือสัญญาณว่า parse เพี้ยน
CONFIDENCE_EVIDENCE_LOW = 0.25
CONFIDENCE_EVIDENCE_HIGH = 0.6

Confidence = Literal["high", "medium", "low"]


def confidence_level(
    text_chars: int, matched_count: int, evidence_count: int
) -> Confidence:
    """ความน่าเชื่อถือของผลวิเคราะห์ จากความยาวข้อความ + สัดส่วนหลักฐานที่ยืนยันได้.

    `matched_count == 0` ไม่ใช่ 0% แต่คือ "ไม่มีสัญญาณด้านหลักฐานให้ใช้" — ตัดสินด้วย
    ความยาวข้อความอย่างเดียว ไม่งั้นผู้สมัครที่ไม่ตรงเกณฑ์สักข้อจะได้ confidence ต่ำ
    ทั้งที่เราอ่านเรซูเม่เขาได้ครบถ้วนดี (คนละเรื่องกัน)
    """
    if text_chars < CONFIDENCE_TEXT_LOW:
        return "low"

    has_evidence_signal = matched_count > 0
    coverage = evidence_count / matched_count if has_evidence_signal else None

    if coverage is not None and coverage < CONFIDENCE_EVIDENCE_LOW:
        return "low"
    if text_chars >= CONFIDENCE_TEXT_HIGH and (
        coverage is None or coverage >= CONFIDENCE_EVIDENCE_HIGH
    ):
        return "high"
    return "medium"
