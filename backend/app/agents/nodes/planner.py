"""Node 5: Interview Planner — ร่างคำถามสัมภาษณ์สำหรับผู้สมัครที่ไปต่อ.

ถ้า HR ตัดสินว่า "rejected" (กรณีคะแนนก้ำกึ่งแล้วถูกปฏิเสธ) จะข้ามการเจนคำถาม.
"""
from app.agents.llm import structured_invoke
from app.agents.models import InterviewPlan
from app.agents.state import HRSystemState

PROMPT = """คุณคือผู้สัมภาษณ์ที่มีประสบการณ์ จงร่างคำถามสัมภาษณ์ 5-7 ข้อสำหรับผู้สมัครตำแหน่ง "{job_title}"
โดยเจาะทั้งจุดแข็งและช่องว่างทักษะต่อไปนี้
- ทักษะที่ผ่าน: {matched}
- ทักษะที่ขาด: {missing}
{similar_block}
แต่ละข้อให้ระบุสองส่วน:
1. question — ตัวคำถาม
2. expected_answer — แนวคำตอบที่ดีควรครอบคลุมประเด็นอะไรบ้าง (2-4 ประเด็นสำคัญ)
   เขียนให้ HR ที่ไม่ได้เชี่ยวชาญสายงานนี้อ่านแล้วตัดสินได้ทันทีว่าคำตอบของผู้สมัครดีพอหรือไม่
   ห้ามเขียนเป็นบทสนทนา ให้เขียนเป็นสาระสำคัญที่ต้องได้ยิน"""


def _similar_block(state: HRSystemState, cid: str) -> str:
    """บริบทจาก retrieval agent (RAG) — ไม่มีก็คืนสตริงว่าง (prompt เดิม ไม่เพิ่ม chat call)."""
    similar = (state.get("similar_candidates") or {}).get(cid) or []
    if not similar:
        return ""
    lines = [
        f"- {s.get('full_name', '?')} (ตำแหน่ง {s.get('job_title', '-')}, คะแนน {s.get('fit_score', '-')})"
        for s in similar
    ]
    return (
        "\nผู้สมัครเก่าที่โปรไฟล์คล้ายกัน (ใช้เป็นบริบทช่วยตั้งคำถามให้เจาะจุดที่คนกลุ่มนี้มักอ่อน):\n"
        + "\n".join(lines)
        + "\n"
    )


def plan_interviews(state: HRSystemState) -> dict:
    evaluation = state["evaluations"][0]
    cid = evaluation["candidate_id"]

    # ถ้า HR ปฏิเสธผู้สมัครคนนี้ ไม่ต้องเจนคำถาม (ปล่อยให้ drafter ร่างอีเมลปฏิเสธ)
    if state.get("hr_decision", {}).get(cid) == "rejected":
        return {"interview_plans": {cid: {"questions": []}}}

    jd = state["analyzed_jd"] or {}
    gaps = evaluation.get("gaps", {})
    plan = structured_invoke(
        PROMPT.format(
            job_title=jd.get("job_title", ""),
            matched=gaps.get("matched_required", []) + gaps.get("matched_preferred", []),
            missing=gaps.get("missing_required", []) + gaps.get("missing_preferred", []),
            similar_block=_similar_block(state, cid),
        ),
        InterviewPlan,
    )
    return {"interview_plans": {cid: plan.model_dump()}}
