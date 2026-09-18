"""Node 3: Candidate Matcher — gap analysis + fit score (deterministic, ไม่เรียก LLM).

Fit score = required 60% + preferred 40% (ตาม CLAUDE.md / บรีฟ) — แต่ถ้า JD ระบุเกณฑ์
แค่ฝั่งเดียว จะเฉลี่ยน้ำหนักใหม่ให้ฝั่งนั้นเป็น 100% ไม่ใช่แจกคะแนนอีกฝั่งให้ฟรี
ตรรกะการเทียบทักษะอยู่ใน app/agents/skills.py (เทียบบนขอบเขตคำ + alias + implication)
"""
from app.agents.bands import REVIEW_FROM, confidence_level
from app.agents.explain import explain_score
from app.agents.skills import canonical, matching_owned, split_matched
from app.agents.state import HRSystemState

# น้ำหนักของสองฝั่ง — เป็น "สัดส่วนความสำคัญ" ไม่ใช่คะแนนตายตัว
# ใช้เป็นตัวหารด้วย จึงเปลี่ยนเป็น 70/30 ได้โดยไม่ต้องแก้ที่อื่น
REQUIRED_WEIGHT = 60
PREFERRED_WEIGHT = 40


def _without_excluded(skills: list[str], excluded: list[str]) -> list[str]:
    """ตัด skill criteria ที่ auditor flag ออกจาก JD ก่อนคำนวณคะแนนใหม่."""
    excluded_canonical = {canonical(s) for s in excluded if s and s.strip()}
    if not excluded_canonical:
        return skills
    return [s for s in skills if canonical(s) not in excluded_canonical]


def _evidence_by_jd_skill(
    matched: list[str], owned: set[str], evidence: dict[str, str]
) -> dict[str, str]:
    """แปลงหลักฐานจาก "คีย์ตามการสะกดในเรซูเม่" เป็น "คีย์ตามการสะกดใน JD".

    จำเป็นเพราะ gap_analysis เก็บข้อความต้นฉบับของ JD (skills.py::split_matched) แต่
    skill_evidence ผูกกับ parsed_resume.skills — JD เขียน "SQL" ผู้สมัครเขียน "PostgreSQL"
    แล้วผ่านด้วย IMPLIES จะจับคู่ตรง ๆ ไม่ได้ ต้องถามผ่านตรรกะเทียบทักษะชุดเดียวกับที่
    ใช้ให้คะแนน (matching_owned) ไม่ใช่เทียบสตริงเอง
    """
    if not evidence:
        return {}
    out: dict[str, str] = {}
    for jd_skill in matched:
        source = matching_owned(jd_skill, owned)
        quote = evidence.get(source) if source else None
        if quote:
            out[jd_skill] = quote
    return out


def compute_fit_score(
    matched_req: list[str],
    missing_req: list[str],
    matched_pref: list[str],
    missing_pref: list[str],
) -> int:
    """คะแนนความเหมาะสม 0-100 — **แหล่งความจริงเดียวของสูตร**.

    แยกออกมาเป็นฟังก์ชันบริสุทธิ์เพราะ scripts/recompute_scores.py เคยคัดลอกสูตรไปไว้เอง
    แล้วหลุดไม่ตรงกันเงียบ ๆ (สคริปต์ยังถือสูตรเก่าอยู่ตอนที่ matcher แก้ไปแล้ว
    ถ้ารันจะเอาบั๊กกลับมาทับคะแนนที่ถูกต้อง) — ห้ามคำนวณคะแนนที่อื่นอีก

    ตัวหารคือจำนวนทักษะ "จริง" หลังกรองคำที่ไม่ใช่ทักษะออกแล้ว (เช่น "product owners")

    คำนวณผ่าน score_breakdown ซึ่งเป็นที่เดียวที่มีน้ำหนักและการเฉลี่ยใหม่ — ที่นี่แค่ปัดเศษ
    """
    return round(score_breakdown(matched_req, missing_req, matched_pref, missing_pref)["total"])


def score_breakdown(
    matched_req: list[str],
    missing_req: list[str],
    matched_pref: list[str],
    missing_pref: list[str],
) -> dict:
    """องค์ประกอบของ fit score ทีละฝั่ง — ที่มาของทั้งคะแนนและแท่งบนหน้ารายละเอียด.

    หน้าเว็บแสดง "ฝั่งไหนได้กี่คะแนน" จากผลของฟังก์ชันนี้ตรง ๆ โดยไม่มีสูตรของตัวเอง
    ถ้าให้ frontend คูณ 60/40 เอง จะเกิดสำเนาสูตรชุดที่สองแบบเดียวกับที่
    scripts/recompute_scores.py เคยหลุดไม่ตรงกันมาแล้ว

    คืน:
      required / preferred : {matched, total, weight, points} หรือ None ถ้า JD ไม่ระบุฝั่งนั้น
                             (None ไม่ใช่ 0/0 — ฝั่งที่ว่างต้องไม่ดูเหมือนผู้สมัครเสียคะแนน)
                             weight คือน้ำหนักหลังเฉลี่ยใหม่เป็นส่วนของ 100 จึงรวมกันได้ 100 เสมอ
      total                : ผลรวม points (ยังไม่ปัด) หรือ REVIEW_FROM ถ้าไม่มีเกณฑ์เลย
      no_criteria          : JD ไม่มีทักษะให้เทียบทั้งสองฝั่ง
    """
    n_req = len(matched_req) + len(missing_req)
    n_pref = len(matched_pref) + len(missing_pref)

    if not n_req and not n_pref:
        # JD ไม่มีทักษะให้เทียบเลย (LLM วิเคราะห์ล้มเหลว หรือสกัดได้แต่ชื่อบทบาท) —
        # สูตรปกติจะให้ 100 ทุกคน แล้ว router จะ auto-advance ไปเชิญสัมภาษณ์ยกแผง
        # จึงบังคับให้ตกแบนด์ "รอ HR" เพื่อให้มนุษย์ตัดสินแทนการเดา
        return {"required": None, "preferred": None, "total": REVIEW_FROM, "no_criteria": True}

    # เฉลี่ยน้ำหนักใหม่ตามฝั่งที่ JD ระบุจริง: 60/40 คือความสำคัญ "เชิงเปรียบเทียบ"
    # ซึ่งมีความหมายก็ต่อเมื่อมีทั้งสองฝั่ง
    # เดิมฝั่งที่ JD ไม่ระบุถูกนับเป็นผ่านเต็ม (ratio 1.0) ทำให้ JD ที่มีแต่ required
    # แจกคะแนนฟรี 40 ให้ทุกคน — ผู้สมัครที่ตรงเกณฑ์ 0/19 ยังได้ 40% ซึ่ง HR อ่านแล้วงง
    # และไม่มีทางอธิบายให้สมเหตุสมผลได้ เพราะคะแนนนั้นไม่ควรมีตั้งแต่แรก
    w_req = REQUIRED_WEIGHT if n_req else 0
    w_pref = PREFERRED_WEIGHT if n_pref else 0
    scale = 100 / (w_req + w_pref)

    def side(matched: list[str], n: int, w: int) -> dict | None:
        if not n:
            return None
        weight = w * scale
        return {
            "matched": len(matched),
            "total": n,
            "weight": weight,
            "points": weight * len(matched) / n,
        }

    required = side(matched_req, n_req, w_req)
    preferred = side(matched_pref, n_pref, w_pref)
    total = sum(s["points"] for s in (required, preferred) if s)
    return {"required": required, "preferred": preferred, "total": total, "no_criteria": False}


def match_candidates(state: HRSystemState) -> dict:
    jd = state["analyzed_jd"] or {}
    profile = state["parsed_resumes"][0]
    cid = profile["candidate_id"]
    owned = {s for s in profile.get("skills", []) if s and s.strip()}
    # ข้อความเรซูเม่ดิบ — ใช้วัดความมั่นใจของผลวิเคราะห์ (กราฟรันทีละคน จึงเป็น [0] เสมอ)
    raw_resumes = state.get("raw_resumes") or [{}]
    resume_text = raw_resumes[0].get("content") or ""

    exclusions = (state.get("bias_exclusions") or {}).get(cid) or {}
    required_skills = _without_excluded(
        jd.get("required_skills") or [], exclusions.get("required_skills") or []
    )
    preferred_skills = _without_excluded(
        jd.get("preferred_skills") or [], exclusions.get("preferred_skills") or []
    )

    matched_req, missing_req = split_matched(required_skills, owned)
    matched_pref, missing_pref = split_matched(preferred_skills, owned)

    fit_score = compute_fit_score(matched_req, missing_req, matched_pref, missing_pref)

    # หลักฐานเฉพาะทักษะที่ "ตรงเกณฑ์" — ทักษะที่ขาดคือไม่มีในเรซูเม่ จึงไม่มีข้อความให้อ้าง
    # (หลักฐานผ่านด่าน filter_evidence ใน resume_parser มาแล้ว ที่นี่แค่เปลี่ยนคีย์)
    skill_evidence = _evidence_by_jd_skill(
        matched_req + matched_pref, owned, profile.get("skill_evidence") or {}
    )

    gaps = {
        "matched_required": matched_req,
        "missing_required": missing_req,
        "matched_preferred": matched_pref,
        "missing_preferred": missing_pref,
    }

    evaluation = {
        "candidate_id": cid,
        "fit_score": fit_score,
        "gaps": gaps,
        # อธิบายตัวเลขที่คำนวณเสร็จแล้วเป็นภาษาคน (template ล้วน ไม่เรียก LLM)
        "score_explanation": explain_score(gaps, fit_score),
        "skill_evidence": skill_evidence,
        # ความน่าเชื่อถือของผลวิเคราะห์ คนละมิติกับ fit_score — นับอักขระที่ไม่ใช่ช่องว่าง
        # ด้วยสูตรเดียวกับ candidates.py::_is_unreadable_resume
        "confidence": confidence_level(
            len("".join(resume_text.split())),
            len(matched_req) + len(matched_pref),
            len(skill_evidence),
        ),
        "is_biased": False,
        "audit_status": "passed",
        "audit_log": "",
    }
    if exclusions:
        # บันทึกร่องรอยของลูป critique/revise ให้เห็นได้จริง: matcher เป็นคนเขียนก้อนนี้
        # (auditor รอบถัดไปคัดลอก evaluation ต่อ จึงติดไปถึง _persist_evaluation)
        # ถ้าไม่เก็บ score ก่อนแก้ หน้าเว็บจะเห็นแต่คะแนนหลังแก้ = ลูปหายไปเฉย ๆ
        previous = (state.get("evaluations") or [{}])[0]
        evaluation["bias_revision"] = {
            "round": (state.get("bias_revision_count") or {}).get(cid, 1),
            "score_before": previous.get("fit_score"),
            "score_after": fit_score,
            "excluded_required": exclusions.get("required_skills") or [],
            "excluded_preferred": exclusions.get("preferred_skills") or [],
            "reason": exclusions.get("reason", ""),
        }

    revision_pending = dict(state.get("bias_revision_pending") or {})
    if cid in revision_pending:
        revision_pending[cid] = False

    return {"evaluations": [evaluation], "bias_revision_pending": revision_pending}
