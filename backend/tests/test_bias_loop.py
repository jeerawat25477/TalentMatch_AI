"""ทดสอบ agent loop bias_auditor -> matcher แบบ critique/revise.

ตั้งแต่ 2026-09-28 ผลตรวจอคติเป็นของ "ตำแหน่ง" ทำครั้งเดียวตอนสร้าง (jobs.jd_audit) แล้วโหนด
bias_auditor อ่านจาก state["jd_audit"] อย่างเดียว **ไม่เรียก LLM** · ลูปนี้ยังต้องจำกัด 1 รอบ
และ matcher คำนวณใหม่แบบ deterministic จากเกณฑ์ที่ผลตรวจขอให้ถอด
"""
import pytest

from app.agents import llm
from app.agents.graph import route_candidates
from app.agents.models import BiasAudit
from app.agents.nodes import bias_auditor
from app.agents.nodes.bias_auditor import build_jd_audit
from app.agents.nodes.matcher import match_candidates


def _state() -> dict:
    return {
        "raw_jd": "ตำแหน่ง Backend Developer\nคุณสมบัติ: Python, เพศชาย อายุไม่เกิน 30 ปี",
        "raw_resumes": [],
        "analyzed_jd": {
            "job_title": "Backend Developer",
            "required_skills": ["Python", "มหาวิทยาลัยชั้นนำ"],
            "preferred_skills": ["Docker"],
        },
        "parsed_resumes": [{"candidate_id": "cand-1", "skills": ["Python", "Docker"]}],
        "evaluations": [],
        "hr_decision": {},
        "hr_notes": {},
        "interview_plans": {},
        "email_drafts": {},
        "similar_candidates": {},
        "bias_revision_count": {},
        "bias_revision_pending": {},
        "bias_exclusions": {},
    }


def _with_audit(state: dict, audit: BiasAudit | None) -> dict:
    """ใส่ผลตรวจของตำแหน่งลง state แบบเดียวกับที่ worker โหลดมาจาก jobs.jd_audit."""
    state["jd_audit"] = build_jd_audit(audit, state["raw_jd"])
    return state


_FLAG_SCHOOL = BiasAudit(
    is_biased=True,
    audit_status="flagged",
    audit_log="พบการใช้สถาบันการศึกษาเป็นเกณฑ์",
    biased_required_skills=["มหาวิทยาลัยชั้นนำ"],
)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """โหนดต้องไม่เรียก LLM เด็ดขาด — ถ้าเรียกเทสต์ทุกข้อในไฟล์นี้ล้มทันที."""

    def boom(*args, **kwargs):
        raise AssertionError("bias_auditor ต้องไม่เรียก LLM ต่อผู้สมัคร")

    monkeypatch.setattr(llm, "structured_invoke", boom)
    monkeypatch.setattr(llm, "structured_invoke_once", boom)
    monkeypatch.setattr(bias_auditor, "structured_invoke_once", boom)


def test_auditor_flags_biased_criterion_and_routes_back_to_matcher():
    state = _with_audit(_state(), _FLAG_SCHOOL)
    state.update(match_candidates(state))

    state.update(bias_auditor.audit_bias(state))

    assert state["bias_revision_count"] == {"cand-1": 1}
    assert state["bias_revision_pending"] == {"cand-1": True}
    assert state["bias_exclusions"]["cand-1"]["required_skills"] == ["มหาวิทยาลัยชั้นนำ"]
    assert route_candidates(state) == "revise"


def test_matcher_applies_auditor_exclusion_and_clears_pending():
    state = _state()
    state["bias_revision_pending"] = {"cand-1": True}
    state["bias_exclusions"] = {
        "cand-1": {
            "required_skills": ["มหาวิทยาลัยชั้นนำ"],
            "preferred_skills": [],
            "reason": "biased criterion",
        }
    }

    out = match_candidates(state)
    evaluation = out["evaluations"][0]

    assert evaluation["fit_score"] == 100
    assert evaluation["gaps"]["missing_required"] == []
    assert evaluation["bias_revision"]["score_after"] == 100
    assert out["bias_revision_pending"] == {"cand-1": False}


def test_auditor_does_not_loop_more_than_once():
    state = _with_audit(_state(), _FLAG_SCHOOL)
    state["bias_revision_count"] = {"cand-1": 1}
    state.update(match_candidates(state))

    state.update(bias_auditor.audit_bias(state))

    assert state["bias_revision_count"] == {"cand-1": 1}
    assert state["bias_revision_pending"] == {"cand-1": False}
    assert route_candidates(state) == "advance"


def test_hr_decision_wins_over_pending_revision():
    state = _state()
    state["evaluations"] = [{"candidate_id": "cand-1", "fit_score": 100}]
    state["bias_revision_pending"] = {"cand-1": True}
    state["hr_decision"] = {"cand-1": "rejected"}

    assert route_candidates(state) == "reject"


def test_full_revise_path_keeps_revision_record():
    """เดินเส้นทางจริงตามที่ graph.py ต่อไว้: matcher -> auditor(flag) -> router
    -> matcher -> auditor(รอบสอง) แล้ว evaluation สุดท้ายต้องยังพก bias_revision ไปถึง DB."""
    state = _with_audit(_state(), _FLAG_SCHOOL)

    state.update(match_candidates(state))
    score_before = state["evaluations"][0]["fit_score"]
    state.update(bias_auditor.audit_bias(state))
    assert route_candidates(state) == "revise"

    state.update(match_candidates(state))
    state.update(bias_auditor.audit_bias(state))

    evaluation = state["evaluations"][0]
    revision = evaluation["bias_revision"]
    assert revision["round"] == 1
    assert revision["score_before"] == score_before
    assert revision["score_after"] == evaluation["fit_score"]
    assert revision["score_after"] > score_before
    assert revision["excluded_required"] == ["มหาวิทยาลัยชั้นนำ"]
    # รอบสองต้องไม่วนอีก แม้ผลตรวจจะยัง flag อยู่
    assert state["bias_revision_count"] == {"cand-1": 1}
    assert route_candidates(state) in {"advance", "reject"}


def test_jd_level_bias_is_reported_even_when_nothing_can_be_recomputed():
    """เกณฑ์อย่าง "เพศชาย/อายุไม่เกิน 30" ถูก jd_analyzer กรองทิ้งก่อนถึง required_skills
    (พิสูจน์กับ Gemini จริงแล้ว) จึงถอดออกจากคะแนนไม่ได้ — ต้องไม่เข้าลูป แต่ต้องเตือน HR."""
    audit = BiasAudit(
        is_biased=True,
        audit_status="flagged",
        audit_log="ประกาศระบุเพศและอายุ",
        biased_jd_criteria=["เพศชาย", "อายุไม่เกิน 30 ปี"],
    )
    state = _with_audit(_state(), audit)
    state.update(match_candidates(state))
    state.update(bias_auditor.audit_bias(state))

    log = state["evaluations"][0]["audit_log"]
    assert "เพศชาย" in log and "อายุไม่เกิน 30 ปี" in log
    # ไม่มี skill ให้ถอด → ห้ามวนกลับ matcher
    assert state["bias_revision_pending"] == {"cand-1": False}
    assert state["bias_revision_count"] == {}
    assert route_candidates(state) in {"advance", "reject"}


# ── ผลตรวจของตำแหน่ง: ทุกผู้สมัครได้ผลเดียวกันตรงตัว ──


def test_every_candidate_in_a_job_gets_the_exact_same_audit():
    audit = _with_audit(_state(), None)["jd_audit"]
    logs = set()
    for cid in ("cand-1", "cand-2", "cand-3"):
        state = _state()
        state["parsed_resumes"] = [{"candidate_id": cid, "skills": ["Python"]}]
        state["jd_audit"] = audit
        state.update(match_candidates(state))
        state.update(bias_auditor.audit_bias(state))
        logs.add(state["evaluations"][0]["audit_log"])
    assert len(logs) == 1


def test_missing_jd_audit_falls_back_to_rules_without_llm():
    """ตำแหน่งเก่า / checkpoint เก่าที่ไม่มี jd_audit → กฎตายตัวอย่างเดียว ฟรี."""
    state = _state()  # ไม่มีคีย์ jd_audit เลย
    state.update(match_candidates(state))
    state.update(bias_auditor.audit_bias(state))

    ev = state["evaluations"][0]
    assert ev["audit_status"] == "flagged"
    assert "เพศชาย" in ev["audit_log"]
    assert state["bias_revision_pending"] == {"cand-1": False}


def test_clean_job_passes():
    state = _state()
    state["raw_jd"] = "ตำแหน่ง Backend Developer\nคุณสมบัติ: Python, Docker"
    state["jd_audit"] = build_jd_audit(
        BiasAudit(is_biased=False, audit_status="passed", audit_log="ไม่พบการใช้ข้อมูลอคติ"),
        state["raw_jd"],
    )
    state.update(match_candidates(state))
    state.update(bias_auditor.audit_bias(state))

    ev = state["evaluations"][0]
    assert ev["is_biased"] is False
    assert ev["audit_status"] == "passed"
    assert ev["audit_log"] == "ไม่พบการใช้ข้อมูลอคติ"
