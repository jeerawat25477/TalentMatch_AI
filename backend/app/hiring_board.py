"""กฎว่าผู้สมัครคนไหนขึ้นกระดานติดตาม — ฟังก์ชันบริสุทธิ์ล้วน ไม่ต่อ DB.

แยกออกมาจากเราเตอร์เพื่อให้ทดสอบได้ทุกกิ่งโดยไม่ต้องมีฐานข้อมูล (แพตเทิร์นเดียวกับ
resume_ingest.is_duplicate_upload, candidates._is_stalled และ llm_quota.quota_date)

**ลำดับความสำคัญต้องตรงกับ agents/graph.py::route_candidates** คือคำตัดสินของ HR
มาก่อนคะแนนเสมอ นั่นคือจุดที่ทำให้ "มนุษย์มีอำนาจสูงสุด" เป็นจริง ไม่ใช่แค่ปุ่มที่กดแล้ว
คะแนนของ AI ยังชนะอยู่ดี

ที่ **ต่างจาก** route_candidates โดยตั้งใจคือเส้นคะแนน: กราฟใช้ is_rejected_by_score
(ตั้งแต่ 50 ขึ้นไปก็เดินต่อไป interview_planner แล้วค่อยหยุดที่ interrupt) ส่วนกระดานนี้
ใช้ should_auto_advance (>70) เพราะกระดานมีไว้ติดตาม "คนที่มีการตัดสินเกิดขึ้นแล้ว"
คนช่วง 50-70 ที่กราฟยังหยุดรออยู่ยังไม่มีใครตัดสิน ถ้าเอาขึ้นกระดานด้วยจะกลายเป็นรายการ
ซ้ำกับแท็บ "Needs Review" ในหน้ารายชื่อ ซึ่งทำหน้าที่นั้นอยู่แล้ว
"""
from typing import Optional

from app.agents.bands import should_auto_advance


def is_board_eligible(
    has_stage_row: bool,
    hr_decision: Optional[str],
    fit_score: Optional[int],
) -> bool:
    """ผู้สมัครคนนี้ควรปรากฏบนกระดานของตำแหน่งนี้ไหม.

    `has_stage_row` มาก่อนทุกอย่าง: การ์ดที่เคยขึ้นกระดานแล้วต้องไม่หายเงียบ ไม่ว่าคะแนน
    หรือคำตัดสินจะเปลี่ยนไปอย่างไรทีหลัง — HR นัดสัมภาษณ์คนคนนั้นไปแล้ว การ์ดที่หายไป
    เองกลางทางแปลว่างานที่ทำไปแล้วหายไปด้วยโดยไม่มีใครรู้ (เคสนั้นขึ้นป้ายเตือนแทน
    ผ่าน has_screening_conflict)
    """
    if has_stage_row:
        return True
    if hr_decision == "rejected":
        return False
    if hr_decision == "approved":
        return True
    return fit_score is not None and should_auto_advance(fit_score)


def has_screening_conflict(
    has_stage_row: bool,
    hr_decision: Optional[str],
    fit_score: Optional[int],
) -> bool:
    """การ์ดอยู่บนกระดาน แต่ตอนนี้ไม่เข้าเกณฑ์แล้ว — ให้ UI ขึ้นป้ายเตือน.

    เกิดเมื่อ HR กลับคำเป็น "ไม่ผ่าน" หลังจากที่การ์ดขึ้นกระดานไปแล้ว หรือคะแนนถูก
    คำนวณใหม่จนตกเกณฑ์ · เราไม่ซ่อนการ์ดทิ้ง (ดูเหตุผลใน is_board_eligible) แต่ต้อง
    บอกให้ HR เห็นว่าสองอย่างนี้ขัดกันอยู่ แล้วให้คนตัดสินเองว่าจะเอาอย่างไรต่อ

    ประกอบจาก is_board_eligible โดยส่ง has_stage_row=False เพื่อถามว่า "ถ้าไม่นับ
    การ์ดที่มีอยู่ คนนี้ยังเข้าเกณฑ์ไหม" — กฎเกณฑ์จึงมีชุดเดียว ไม่ใช่สองสำเนาที่หลุดกันได้
    """
    return has_stage_row and not is_board_eligible(False, hr_decision, fit_score)


def board_stage(
    stage_row: Optional[str],
    has_employee: bool,
    hr_decision: Optional[str],
    fit_score: Optional[int],
) -> Optional[str]:
    """ขั้นบนกระดานของผู้สมัครหนึ่งคน หรือ None ถ้าไม่อยู่บนกระดาน.

    แหล่งเดียวที่ทั้ง GET /jobs/{id}/board และหน้ารายละเอียดผู้สมัครใช้ — ก่อนหน้านี้
    หน้ารายละเอียดไม่รู้ขั้นเลย HR จึงเห็นแค่ "อนุมัติแล้ว" ค้างไว้ ขณะที่กระดานบอกว่า
    ยื่นข้อเสนอไปแล้ว ถ้าสองหน้าคำนวณกันเองก็จะหลุดไม่ตรงกันอีกแบบหนึ่ง

    - มีระเบียนพนักงาน -> 'hired' เสมอ (มาก่อน stage_row ดูเหตุผลใน get_board)
    - ไม่มีแถวและไม่เข้าเกณฑ์ -> None
    - เข้าเกณฑ์แต่ยังไม่เคยย้าย -> 'invited' แบบคำนวณ ไม่ใช่แถวจริง
    """
    if has_employee:
        return "hired"
    if not is_board_eligible(stage_row is not None, hr_decision, fit_score):
        return None
    return stage_row or "invited"
