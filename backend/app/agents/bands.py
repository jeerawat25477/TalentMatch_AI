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
