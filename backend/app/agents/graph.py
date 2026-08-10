"""ประกอบกราฟ TalentMatch: nodes + edges + router + checkpointer.

Router หลัง bias_auditor:
- HR ตัดสินไว้แล้ว   → เชื่อ HR ก่อนเสมอ (approved → advance, rejected → reject)
- fit > 70          → advance ... interrupt จะพักก่อน interview_planner เสมอ
- 50 ≤ fit ≤ 70     → advance เช่นกัน แต่ runner จะ "รอ" ไม่ auto-resume
- fit < 50          → reject → email_drafter

**ทำไม router ต้องดู hr_decision:** ถ้าดูแต่คะแนน HR จะกู้คนที่ถูกตัดอัตโนมัติ (fit<50)
ไม่ได้เลย เพราะเส้นทางนั้นไม่เคยแวะ interrupt — กราฟจบไปแล้วตั้งแต่แรก
runner.resume_after_decision จะย้อน state กลับมาที่ bias_auditor แล้วให้ router
ตัดสินใหม่โดยมี hr_decision อยู่ในมือ ดูรายละเอียดที่ runner.py

เส้นแบ่งคะแนนทั้งหมดอยู่ที่ app/agents/bands.py ที่เดียว — ห้าม hardcode 50/70 ที่นี่
"""
from langgraph.graph import END, StateGraph

from app.agents.bands import is_rejected_by_score
from app.agents.nodes import (
    analyze_jd,
    audit_bias,
    draft_emails,
    match_candidates,
    parse_resumes,
    plan_interviews,
    retrieve_similar,
)
from app.agents.state import HRSystemState
from app.database import get_checkpointer


def route_candidates(state: HRSystemState) -> str:
    """ตัดสินเส้นทางหลัง bias_auditor (รันต่อผู้สมัคร → ดู evaluation ตัวเดียว).

    คำตัดสินของ HR มาก่อนคะแนนเสมอ — นี่คือจุดที่ทำให้ "มนุษย์มีอำนาจสูงสุด"
    เป็นจริง แทนที่จะเป็นแค่ปุ่มที่กดแล้วคะแนนของ AI ยังชนะอยู่ดี
    """
    evaluation = state["evaluations"][0]
    decision = (state.get("hr_decision") or {}).get(evaluation["candidate_id"])
    if decision == "approved":
        return "advance"
    if decision == "rejected":
        return "reject"
    return "reject" if is_rejected_by_score(evaluation["fit_score"]) else "advance"


def build_graph() -> StateGraph:
    workflow = StateGraph(HRSystemState)
    workflow.add_node("jd_analyzer", analyze_jd)
    workflow.add_node("resume_parser", parse_resumes)
    workflow.add_node("retrieve_similar", retrieve_similar)  # RAG agent (เปิด/ปิดด้วย RAG_ENABLED)
    workflow.add_node("matcher", match_candidates)
    workflow.add_node("bias_auditor", audit_bias)
    workflow.add_node("interview_planner", plan_interviews)
    workflow.add_node("email_drafter", draft_emails)

    workflow.set_entry_point("jd_analyzer")
    workflow.add_edge("jd_analyzer", "resume_parser")
    workflow.add_edge("resume_parser", "retrieve_similar")
    workflow.add_edge("retrieve_similar", "matcher")
    workflow.add_edge("matcher", "bias_auditor")
    workflow.add_conditional_edges(
        "bias_auditor",
        route_candidates,
        {"advance": "interview_planner", "reject": "email_drafter"},
    )
    workflow.add_edge("interview_planner", "email_drafter")
    workflow.add_edge("email_drafter", END)
    return workflow


_compiled = None


def get_graph():
    """คืนกราฟที่ compile แล้ว (singleton) พร้อม PostgresSaver + interrupt HITL."""
    global _compiled
    if _compiled is None:
        _compiled = build_graph().compile(
            checkpointer=get_checkpointer(),
            interrupt_before=["interview_planner"],
        )
    return _compiled
