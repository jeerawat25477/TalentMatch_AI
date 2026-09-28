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
    # Bias critique/revise loop (จำกัดรอบใน graph.py): auditor เสนอ criteria ที่ควรถอด,
    # matcher คำนวณใหม่แบบ deterministic แล้ว auditor ตรวจซ้ำ
    bias_revision_count: Dict[str, int]  # {candidate_id: จำนวนรอบ revise ที่ใช้ไป}
    bias_revision_pending: Dict[str, bool]  # {candidate_id: auditor ขอให้ matcher revise รอบถัดไป}
    bias_exclusions: Dict[str, Any]  # {candidate_id: {"required_skills": [], "preferred_skills": [], "reason": str}}
    # ผลตรวจอคติของ "ตำแหน่ง" (jobs.jd_audit) ที่ทำครั้งเดียวตอนสร้างตำแหน่ง — auditor อ่านอย่างเดียว
    # ไม่เรียก LLM ต่อผู้สมัคร · อ่านด้วย .get เสมอ: checkpoint ที่บันทึกก่อนมีฟิลด์นี้ไม่มีคีย์นี้
    # รูป: {status, log, jd_criteria, biased_required_skills, biased_preferred_skills, llm_checked}
    jd_audit: Optional[Dict[str, Any]]

    # RAG: ผู้สมัครเก่าที่โปรไฟล์คล้ายกัน (retrieval agent เติม, เปิด/ปิดด้วย RAG_ENABLED)
    similar_candidates: Dict[str, Any]  # {candidate_id: [{id, full_name, job_title, fit_score, distance}, ...]}

    # Human-in-the-Loop Decisions
    hr_decision: Dict[str, str]  # {candidate_id: "approved" | "rejected" | "pending"}
    hr_notes: Dict[str, str]

    # Outputs
    interview_plans: Dict[str, Any]  # {candidate_id: {...}}
    email_drafts: Dict[str, Any]     # {candidate_id: {...}}
