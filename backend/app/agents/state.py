"""นิยาม State เดียวของทั้งกราฟ (คัดจาก backend_langgraph.md — ห้าม drift).

หมายเหตุการใช้งาน: เรารันกราฟ "ต่อผู้สมัครหนึ่งคน" (thread_id = candidate_id)
ดังนั้น raw_resumes / parsed_resumes / evaluations จะมีสมาชิกเพียง 1 รายการต่อรัน
โครงสร้าง (list/dict) ยังเหมือนบรีฟทุกประการ.
"""
from typing import Any, Dict, List, Optional, TypedDict


class HRSystemState(TypedDict):
    # Inputs
    raw_jd: str
    raw_resumes: List[Dict[str, Any]]  # [{"candidate_id": str, "filename": str, "content": str}]

    # Parsed Data
    analyzed_jd: Optional[Dict[str, Any]]
    parsed_resumes: List[Dict[str, Any]]

    # Evaluations
    evaluations: List[Dict[str, Any]]  # {"candidate_id","fit_score","gaps","is_biased","audit_status","audit_log"}

    # RAG: ผู้สมัครเก่าที่โปรไฟล์คล้ายกัน (retrieval agent เติม, เปิด/ปิดด้วย RAG_ENABLED)
    similar_candidates: Dict[str, Any]  # {candidate_id: [{id, full_name, job_title, fit_score, distance}, ...]}

    # Human-in-the-Loop Decisions
    hr_decision: Dict[str, str]  # {candidate_id: "approved" | "rejected" | "pending"}
    hr_notes: Dict[str, str]

    # Outputs
    interview_plans: Dict[str, Any]  # {candidate_id: {...}}
    email_drafts: Dict[str, Any]     # {candidate_id: {...}}
