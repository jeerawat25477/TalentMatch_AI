"""Node 6: Email Drafter — ร่างอีเมลเชิญสัมภาษณ์ หรือปฏิเสธ ตามผลลัพธ์.

เลือกชนิดอีเมล (คำตัดสินของ HR ชนะคะแนนเสมอ):
- HR ตัดสินแล้ว → ตามนั้น (approved = invitation, rejected = rejection)
- ยังไม่ตัดสิน   → ดูคะแนน: fit < 50 = rejection, นอกนั้น = invitation

⚠️ prompt ได้แค่ชื่อผู้สมัครกับชื่อตำแหน่ง — ไม่มีเรซูเม่ ไม่มีคะแนน ไม่มีเหตุผลที่ไม่ผ่าน
อีเมลปฏิเสธจึงอ้างเหตุผลส่วนตัวไม่ได้ (tests/test_prompt_privacy.py ล็อกไว้) · ข้อความที่ HR แก้เอง
ถูกตรวจอีกชั้นตอนกดส่ง (routers/hr.py::send_candidate_email)
"""
from app.agents.bands import is_rejected_by_score
from app.agents.llm import structured_invoke
from app.agents.models import EmailDraft
from app.agents.state import HRSystemState

INVITE_PROMPT = """ร่างอีเมลเชิญสัมภาษณ์อย่างสุภาพและอบอุ่นสำหรับผู้สมัคร {name}
ตำแหน่ง "{job_title}" ระบุ subject และ body (ภาษาไทย). kind = "invitation"."""

REJECT_PROMPT = """ร่างอีเมลแจ้งผลว่ายังไม่ผ่านการพิจารณาอย่างสุภาพและให้เกียรติสำหรับผู้สมัคร {name}
ตำแหน่ง "{job_title}" ระบุ subject และ body (ภาษาไทย). kind = "rejection"."""


def draft_emails(state: HRSystemState) -> dict:
    evaluation = state["evaluations"][0]
    cid = evaluation["candidate_id"]
    profile = state["parsed_resumes"][0]
    jd = state["analyzed_jd"] or {}

    # HR ตัดสินแล้วต้องมาก่อนคะแนนเสมอ (ตรงกับ route_candidates) — ถ้า HR อนุมัติคนคะแนนต่ำ
    # ต้องได้อีเมลเชิญ ไม่ใช่อีเมลปฏิเสธที่ขัดกับคำถามสัมภาษณ์ที่ planner เพิ่งสร้าง
    decision = (state.get("hr_decision") or {}).get(cid)
    if decision == "approved":
        is_reject = False
    elif decision == "rejected":
        is_reject = True
    else:
        is_reject = is_rejected_by_score(evaluation["fit_score"])
    prompt = (REJECT_PROMPT if is_reject else INVITE_PROMPT).format(
        name=profile.get("full_name", "ผู้สมัคร"), job_title=jd.get("job_title", "")
    )
    draft = structured_invoke(prompt, EmailDraft)
    return {"email_drafts": {cid: draft.model_dump()}}
