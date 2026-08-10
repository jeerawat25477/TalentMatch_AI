"""Node 3: Candidate Matcher — gap analysis + fit score (deterministic, ไม่เรียก LLM).

Fit score = required 60% + preferred 40% (ตาม CLAUDE.md / บรีฟ).
ตรรกะการเทียบทักษะอยู่ใน app/agents/skills.py (เทียบบนขอบเขตคำ + alias + implication)
"""
from app.agents.bands import REVIEW_FROM
from app.agents.skills import split_matched
from app.agents.state import HRSystemState


def match_candidates(state: HRSystemState) -> dict:
    jd = state["analyzed_jd"] or {}
    profile = state["parsed_resumes"][0]
    owned = {s for s in profile.get("skills", []) if s and s.strip()}

    matched_req, missing_req = split_matched(jd.get("required_skills") or [], owned)
    matched_pref, missing_pref = split_matched(jd.get("preferred_skills") or [], owned)

    # ตัวหารคือจำนวนทักษะ "จริง" หลังกรองคำที่ไม่ใช่ทักษะออกแล้ว (เช่น "product owners")
    # ถ้า JD ไม่ระบุทักษะฝั่งใดเลย ให้ถือว่าผ่านฝั่งนั้นเต็ม — คงพฤติกรรมเดิม
    n_req = len(matched_req) + len(missing_req)
    n_pref = len(matched_pref) + len(missing_pref)
    req_ratio = len(matched_req) / n_req if n_req else 1.0
    pref_ratio = len(matched_pref) / n_pref if n_pref else 1.0

    if not n_req and not n_pref:
        # JD ไม่มีทักษะให้เทียบเลย (LLM วิเคราะห์ล้มเหลว หรือสกัดได้แต่ชื่อบทบาท) —
        # สูตรปกติจะให้ 100 ทุกคน แล้ว router จะ auto-advance ไปเชิญสัมภาษณ์ยกแผง
        # จึงบังคับให้ตกแบนด์ "รอ HR" เพื่อให้มนุษย์ตัดสินแทนการเดา
        fit_score = REVIEW_FROM
    else:
        fit_score = round(60 * req_ratio + 40 * pref_ratio)

    evaluation = {
        "candidate_id": profile["candidate_id"],
        "fit_score": fit_score,
        "gaps": {
            "matched_required": matched_req,
            "missing_required": missing_req,
            "matched_preferred": matched_pref,
            "missing_preferred": missing_pref,
        },
        "is_biased": False,
        "audit_status": "passed",
        "audit_log": "",
    }
    return {"evaluations": [evaluation]}
