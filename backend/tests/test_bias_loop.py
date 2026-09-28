"""ทดสอบ agent loop bias_auditor -> matcher แบบ critique/revise.

ลูปนี้ต้องจำกัด 1 รอบและไม่เรียก LLM ในเทสต์: auditor ถูก stub ให้คืน structured output
แล้ว matcher คำนวณใหม่แบบ deterministic จาก criteria ที่ auditor ขอให้ถอด.
"""
from app.agents.graph import route_candidates
from app.agents.models import BiasAudit
from app.agents.nodes import bias_auditor
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


def test_auditor_flags_biased_criterion_and_routes_back_to_matcher(monkeypatch):
    def fake_invoke(*args, **kwargs):
        return BiasAudit(
            is_biased=True,
            audit_status="flagged",
            audit_log="พบการใช้สถาบันการศึกษาเป็นเกณฑ์",
            biased_required_skills=["มหาวิทยาลัยชั้นนำ"],
        )

    state = _state()
    state.update(match_candidates(state))
    monkeypatch.setattr(bias_auditor, "structured_invoke", fake_invoke)

    out = bias_auditor.audit_bias(state)
    state.update(out)

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


def test_auditor_does_not_loop_more_than_once(monkeypatch):
    def fake_invoke(*args, **kwargs):
        return BiasAudit(
            is_biased=True,
            audit_status="flagged",
            audit_log="ยังพบเกณฑ์ที่ควรระวัง",
            biased_required_skills=["มหาวิทยาลัยชั้นนำ"],
        )

    state = _state()
    state["bias_revision_count"] = {"cand-1": 1}
    state.update(match_candidates(state))
    monkeypatch.setattr(bias_auditor, "structured_invoke", fake_invoke)

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


def test_full_revise_path_keeps_revision_record(monkeypatch):
    """เดินเส้นทางจริงตามที่ graph.py ต่อไว้: matcher -> auditor(flag) -> router
    -> matcher -> auditor(รอบสอง) แล้ว evaluation สุดท้ายต้องยังพก bias_revision ไปถึง DB."""

    def fake_invoke(*args, **kwargs):
        return BiasAudit(
            is_biased=True,
            audit_status="flagged",
            audit_log="พบการใช้สถาบันการศึกษาเป็นเกณฑ์",
            biased_required_skills=["มหาวิทยาลัยชั้นนำ"],
        )

    monkeypatch.setattr(bias_auditor, "structured_invoke", fake_invoke)
    state = _state()

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
    # รอบสองต้องไม่วนอีก แม้ auditor จะ flag ซ้ำ
    assert state["bias_revision_count"] == {"cand-1": 1}
    assert route_candidates(state) in {"advance", "reject"}


def test_jd_level_bias_is_reported_even_when_nothing_can_be_recomputed(monkeypatch):
    """เกณฑ์อย่าง "เพศชาย/อายุไม่เกิน 30" ถูก jd_analyzer กรองทิ้งก่อนถึง required_skills
    (พิสูจน์กับ Gemini จริงแล้ว) จึงถอดออกจากคะแนนไม่ได้ — ต้องไม่เข้าลูป แต่ต้องเตือน HR."""

    def fake_invoke(*args, **kwargs):
        return BiasAudit(
            is_biased=True,
            audit_status="flagged",
            audit_log="ประกาศระบุเพศและอายุ",
            biased_jd_criteria=["เพศชาย", "อายุไม่เกิน 30 ปี"],
        )

    monkeypatch.setattr(bias_auditor, "structured_invoke", fake_invoke)
    state = _state()
    state.update(match_candidates(state))
    state.update(bias_auditor.audit_bias(state))

    log = state["evaluations"][0]["audit_log"]
    assert "เพศชาย" in log and "อายุไม่เกิน 30 ปี" in log
    # ไม่มี skill ให้ถอด → ห้ามวนกลับ matcher (จะเสีย chat call ฟรี ๆ)
    assert state["bias_revision_pending"] == {"cand-1": False}
    assert state["bias_revision_count"] == {}
    assert route_candidates(state) in {"advance", "reject"}


# ── ด่านกฎตายตัว (bias_rules.py) ต่อเข้ากับ auditor ──


def _passed(*args, **kwargs):
    return BiasAudit(is_biased=False, audit_status="passed", audit_log="ไม่พบการใช้ข้อมูลอคติ")


def test_rules_flag_what_the_llm_missed_without_contradicting_itself(monkeypatch):
    """LLM ตอบ passed แต่ประกาศเขียน "เพศชาย" ไว้ตรง ๆ → ต้อง flagged และข้อความต้องไม่ขัดกันเอง."""
    monkeypatch.setattr(bias_auditor, "structured_invoke", _passed)
    state = _state()
    state.update(match_candidates(state))
    state.update(bias_auditor.audit_bias(state))

    ev = state["evaluations"][0]
    assert ev["is_biased"] is True
    assert ev["audit_status"] == "flagged"
    assert "ไม่พบ" not in ev["audit_log"]
    assert "เพศชาย" in ev["audit_log"] and "อายุไม่เกิน 30 ปี" in ev["audit_log"]
    # กฎไม่เพิ่มเกณฑ์ทักษะให้ถอด → ห้ามวนกลับ matcher (เสีย call ฟรี ๆ)
    assert state["bias_revision_pending"] == {"cand-1": False}
    assert route_candidates(state) in {"advance", "reject"}


def test_rules_do_not_duplicate_what_the_llm_already_reported(monkeypatch):
    def fake_invoke(*args, **kwargs):
        return BiasAudit(
            is_biased=True,
            audit_status="flagged",
            audit_log="ประกาศระบุเพศและอายุ",
            biased_jd_criteria=["เพศชาย อายุไม่เกิน 30 ปี"],
        )

    monkeypatch.setattr(bias_auditor, "structured_invoke", fake_invoke)
    state = _state()
    state.update(match_candidates(state))
    state.update(bias_auditor.audit_bias(state))

    log = state["evaluations"][0]["audit_log"]
    # ข้อความของ LLM ถูกเก็บไว้ ไม่ถูกแทน เพราะมัน flagged เองอยู่แล้ว
    assert log.startswith("ประกาศระบุเพศและอายุ")
    warning = log.splitlines()[-1]
    assert warning.count("เพศชาย") == 1
    assert warning.count("อายุไม่เกิน 30") == 1


def test_clean_jd_with_passed_llm_is_unchanged(monkeypatch):
    monkeypatch.setattr(bias_auditor, "structured_invoke", _passed)
    state = _state()
    state["raw_jd"] = "ตำแหน่ง Backend Developer\nคุณสมบัติ: Python, Docker"
    state.update(match_candidates(state))
    state.update(bias_auditor.audit_bias(state))

    ev = state["evaluations"][0]
    assert ev["is_biased"] is False
    assert ev["audit_status"] == "passed"
    assert ev["audit_log"] == "ไม่พบการใช้ข้อมูลอคติ"


def test_rules_read_the_full_jd_not_the_truncated_prompt_copy(monkeypatch):
    """กฎไม่เสีย token จึงอ่านประกาศเต็ม — อคติที่อยู่ท้ายประกาศยาว ๆ ต้องไม่หลุด."""
    monkeypatch.setattr(bias_auditor, "structured_invoke", _passed)
    state = _state()
    state["raw_jd"] = "ตำแหน่ง Backend Developer\n" + ("รายละเอียดงาน " * 600) + "\nสถานภาพโสด"
    assert len(state["raw_jd"]) > bias_auditor._MAX_JD_CHARS
    state.update(match_candidates(state))
    state.update(bias_auditor.audit_bias(state))

    assert "สถานภาพโสด" in state["evaluations"][0]["audit_log"]
