"""ทักษะที่ AI ชี้ว่ามีอคติ (jd_audit.biased_*_skills) — ยืนยันได้ ลบแล้วหายเตือน คะแนนตามกติกาเดียวกับกราฟ.

ช่องโหว่ที่ปิด 2026-10-14: ลูปตรวจอคติตัดทักษะพวกนี้ทุกครั้ง HR ยืนยันไม่ได้ และลบออกจากเกณฑ์แล้ว
คำเตือนก็ไม่หาย · ไม่เรียก LLM เลยทั้งไฟล์
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Json

from app.agents.nodes.bias_auditor import audit_bias
from app.agents.nodes.matcher import evaluate_skills
from app.auth import get_current_user
from app.bias_ack import (
    audit_for_graph, bias_view, effective_biased_skills, llm_skill_phrases, validate_acks, warned_phrases,
)
from app.database import get_conn
from app.main import app

NOW = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
REASON = "งานขับรถส่งของ กฎหมายกำหนดให้มีใบขับขี่ประเภทนี้"
# AI ชี้ผิด (ตัวอย่างที่เป็นไปได้จริง) — กฎตายตัวไม่จับคำนี้ HR ควรยืนยันได้
SKILL = "ใบขับขี่ ท.2"
# AI ชี้ และกฎตายตัวจับด้วย — ถอนแล้วต้องลบออกจากเกณฑ์ (กติกาเดียวกับทักษะที่ HR พิมพ์เอง)
RULE_SKILL = "มหาวิทยาลัยชั้นนำ"
AUDIT = {
    "status": "flagged", "log": "AI ชี้ว่าเกณฑ์ทักษะมีอคติ", "jd_criteria": [],
    "biased_required_skills": [SKILL], "biased_preferred_skills": [], "llm_checked": True,
}
CRIT = {"required_skills": ["Python", SKILL], "preferred_skills": []}


def _ack(phrase, reason=REASON):
    return {"phrase": phrase, "reason": reason, "by": "hr1", "at": NOW.isoformat()}


# ── effective_biased_skills: ตัวเดียวที่บอกว่าตอนนี้ต้องตัดอะไร ──


class TestEffective:
    def test_ยังไม่ยืนยัน_ต้องตัด(self):
        assert effective_biased_skills(AUDIT, [], CRIT)["required_skills"] == [SKILL]

    def test_ยืนยันที่ชื่อทักษะแล้ว_ไม่ตัด(self):
        assert effective_biased_skills(AUDIT, [_ack(SKILL)], CRIT)["required_skills"] == []

    def test_ลบออกจากเกณฑ์แล้ว_ไม่มีอะไรให้ตัด(self):
        crit = {"required_skills": ["Python"], "preferred_skills": []}
        assert effective_biased_skills(AUDIT, [], crit)["required_skills"] == []

    def test_HR_แก้ตัวพิมพ์_ยังนับว่ามีอยู่(self):
        audit = {**AUDIT, "biased_required_skills": ["Native English Speaker"]}
        crit = {"required_skills": ["native english speaker"], "preferred_skills": []}
        assert effective_biased_skills(audit, [], crit)["required_skills"] == ["Native English Speaker"]

    def test_อยู่ในกลุ่ม_A_หรือ_B_ยังนับว่ามีอยู่(self):
        crit = {"required_skills": [f"{SKILL} | สถาบันเทียบเท่า"], "preferred_skills": []}
        assert effective_biased_skills(AUDIT, [], crit)["required_skills"] == [SKILL]

    def test_ไม่รู้เกณฑ์_ถือว่ายังอยู่ทุกตัว(self):
        assert effective_biased_skills(AUDIT, [], None)["required_skills"] == [SKILL]

    def test_ยืนยันที่ถ้อยคำในประกาศที่ตรงกัน_ครอบคลุมทักษะด้วย(self):
        audit = {**AUDIT, "jd_criteria": ["ต้องมีใบขับขี่ ท.2"]}
        assert effective_biased_skills(audit, [_ack("ต้องมีใบขับขี่ ท.2")], CRIT)["required_skills"] == []

    def test_ไม่มีผลตรวจ(self):
        assert effective_biased_skills(None, [], CRIT) == {"required_skills": [], "preferred_skills": []}


class TestWarnedPhrases:
    def test_ทักษะที่ซ้ำกับถ้อยคำในประกาศ_ไม่ขึ้นซ้ำสองที่(self):
        audit = {**AUDIT, "jd_criteria": ["ต้องมีใบขับขี่ ท.2"]}
        assert llm_skill_phrases(audit, CRIT) == []
        assert warned_phrases(audit, CRIT) == ["ต้องมีใบขับขี่ ท.2"]

    def test_ยืนยันชื่อที่แต่งเองถูกทิ้ง_ยืนยันชื่อจริงได้(self):
        out = validate_acks(
            [{"phrase": "ทักษะที่ไม่เคยถูกเตือน", "reason": REASON}, {"phrase": SKILL, "reason": REASON}],
            warned_phrases(AUDIT, CRIT), "hr1", NOW,
        )
        assert [a["phrase"] for a in out] == [SKILL]

    def test_ทักษะที่ลบออกจากเกณฑ์แล้ว_ยืนยันไม่ได้(self):
        assert warned_phrases(AUDIT, {"required_skills": ["Python"], "preferred_skills": []}) == []


class TestView:
    def test_ค้างเตือน(self):
        v = bias_view(AUDIT, [], CRIT)
        assert v["status"] == "flagged" and v["biased_skills"] == [SKILL]

    def test_ยืนยันแล้ว_ย้ายไปรายการยืนยัน_นับคะแนน(self):
        v = bias_view(AUDIT, [_ack(SKILL)], CRIT)
        assert v["status"] == "passed" and v["biased_skills"] == []
        [a] = v["acknowledged"]
        assert a["phrase"] == SKILL and a["kind"] == "skill" and a["scored"] is True

    def test_ลบออกจากเกณฑ์แล้ว_คำเตือนหาย(self):
        v = bias_view(AUDIT, [], {"required_skills": ["Python"], "preferred_skills": []})
        assert v["status"] == "passed" and v["biased_skills"] == []

    def test_ถ้อยคำในประกาศยังเป็น_kind_phrase(self):
        audit = {**AUDIT, "jd_criteria": ["เพศหญิง"]}
        [a] = bias_view(audit, [_ack("เพศหญิง")], CRIT)["acknowledged"]
        assert a["kind"] == "phrase"


# ── กราฟ: โหนดไม่ต้องรู้เรื่องการยืนยัน รับ jd_audit ที่กรองแล้ว ──


def _audit_state(jd_audit):
    return {"evaluations": [{"candidate_id": "c1", "fit_score": 50}], "jd_audit": jd_audit}


class TestGraph:
    def test_ยังไม่ยืนยัน_ลูปตัด(self):
        out = audit_bias(_audit_state(audit_for_graph(AUDIT, [], CRIT)))
        assert out["bias_revision_pending"]["c1"] is True
        assert out["bias_exclusions"]["c1"]["required_skills"] == [SKILL]

    def test_ยืนยันแล้ว_ไม่วนลูป(self):
        out = audit_bias(_audit_state(audit_for_graph(AUDIT, [_ack(SKILL)], CRIT)))
        assert out["bias_revision_pending"]["c1"] is False

    def test_ลบออกจากเกณฑ์แล้ว_ไม่วนลูป(self):
        crit = {"required_skills": ["Python"], "preferred_skills": []}
        out = audit_bias(_audit_state(audit_for_graph(AUDIT, [], crit)))
        assert out["bias_revision_pending"]["c1"] is False

    def test_รูป_jd_audit_เดิมทุกช่อง(self):
        assert set(audit_for_graph(AUDIT, [], CRIT)) == set(AUDIT)
        assert audit_for_graph(None, [], CRIT) is None


# ── API: ยืนยัน/ถอนแล้วคะแนนคนเดิมตามทัน ──


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: "hr-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def job():
    """ตำแหน่งที่ AI ชี้ SKILL ว่ามีอคติ + ผู้สมัคร 1 คน (มี Python ไม่มี SKILL) ที่ลูปตัดไปแล้ว = 100."""
    parsed = {"job_title": "เทสทักษะอคติ (ลบได้)", "min_experience_years": 0, "education": "", **CRIT}
    profile = {"skills": ["Python"]}
    r = evaluate_skills(CRIT["required_skills"], [], profile, "x", {"required_skills": [SKILL]})
    with get_conn() as conn:
        j = conn.execute(
            """INSERT INTO jobs (title, raw_text, parsed_criteria, jd_audit)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            ("เทสทักษะอคติ (ลบได้)", "Python, ใบขับขี่ ท.2", Json(parsed), Json(AUDIT)),
        ).fetchone()
        c = conn.execute(
            """INSERT INTO candidates (job_id, full_name, raw_resume_text, parsed_resume)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            (j["id"], "ผู้สมัครเทสทักษะอคติ", "x", Json(profile)),
        ).fetchone()
        conn.execute(
            """INSERT INTO evaluations (job_id, candidate_id, fit_score, gap_analysis, bias_revision)
               VALUES (%s, %s, %s, %s, %s)""",
            (j["id"], c["id"], r["fit_score"], Json(r["gaps"]),
             Json({"round": 1, "excluded_required": [SKILL], "excluded_preferred": []})),
        )
        conn.commit()
    yield str(j["id"]), str(c["id"])
    with get_conn() as conn:
        conn.execute("DELETE FROM jobs WHERE id = %s", (j["id"],))
        conn.commit()


def _score(cid):
    with get_conn() as conn:
        return conn.execute(
            "SELECT fit_score FROM evaluations WHERE candidate_id = %s", (cid,)
        ).fetchone()["fit_score"]


def _put(client, jid, acks):
    return client.put(f"/api/v1/jobs/{jid}/bias-acknowledgements", json={"acks": acks})


def test_พรีวิวบอกผลต่อคะแนนโดยไม่เขียนอะไร(client, job):
    jid, cid = job
    assert _score(cid) == 100
    res = client.post(f"/api/v1/jobs/{jid}/bias-acknowledgements/preview",
                      json={"acks": [{"phrase": SKILL, "reason": REASON}]})
    assert res.status_code == 200
    [i] = res.json()["impact"]
    assert (i["old_score"], i["new_score"]) == (100, 50)
    assert _score(cid) == 100
    with get_conn() as conn:
        acks = conn.execute("SELECT bias_acknowledgements FROM jobs WHERE id = %s", (jid,)).fetchone()
    assert acks["bias_acknowledgements"] == []


def test_ยืนยันแล้วคนเดิมนับทักษะนั้น_ถอนแล้วตัดกลับ(client, job):
    jid, cid = job
    res = _put(client, jid, [{"phrase": SKILL, "reason": REASON}])
    assert res.status_code == 200
    bias = res.json()["bias"]
    assert bias["status"] == "passed" and bias["acknowledged"][0]["kind"] == "skill"
    assert _score(cid) == 50  # SKILL นับแล้ว ผู้สมัครไม่มี → ได้ครึ่งเดียว
    assert _put(client, jid, []).status_code == 200
    assert _score(cid) == 100  # ถอน = ลูปตัดกลับ (ไม่ต้องบล็อกการถอน เพราะสถานะไม่ยืนยันคือสถานะที่ปลอดภัย)


def test_ยืนยันชื่อที่แต่งเองถูกทิ้ง_คะแนนไม่ขยับ(client, job):
    jid, cid = job
    res = _put(client, jid, [{"phrase": "ของแต่งเอง", "reason": REASON}])
    assert res.status_code == 200 and res.json()["bias"]["acknowledged"] == []
    assert _score(cid) == 100


def test_ลบทักษะด้วยหน้าแก้เกณฑ์แล้วคำเตือนหาย(client, job):
    jid, _ = job
    before = client.get(f"/api/v1/jobs/{jid}").json()["bias"]
    assert before["biased_skills"] == [SKILL]
    res = client.put(f"/api/v1/jobs/{jid}/criteria",
                     json={"required_skills": ["Python"], "preferred_skills": []})
    assert res.status_code == 200
    after = client.get(f"/api/v1/jobs/{jid}").json()["bias"]
    assert after["biased_skills"] == [] and after["status"] == "passed"


def test_แก้เกณฑ์ข้ออื่นหลังยืนยัน_ทักษะยังนับคะแนน(client, job):
    """หน้าแก้เกณฑ์ใช้การยืนยันของตำแหน่ง ไม่ใช่บันทึกเก่าของลูป — ไม่งั้นยืนยันแล้วก็โดนตัดตอนแก้เกณฑ์."""
    jid, cid = job
    _put(client, jid, [{"phrase": SKILL, "reason": REASON}])
    res = client.put(f"/api/v1/jobs/{jid}/criteria",
                     json={"required_skills": ["Python", SKILL], "preferred_skills": ["Docker"]})
    assert res.status_code == 200
    assert _score(cid) < 100  # SKILL ยังนับ (ถ้าถูกตัดตามบันทึกเก่า ผู้สมัครจะได้เต็มฝั่งต้องมี)


def test_ถ้อยคำในประกาศอย่างเดียว_ไม่แตะคะแนน(client, job):
    jid, cid = job
    with get_conn() as conn:
        conn.execute("UPDATE jobs SET jd_audit = %s WHERE id = %s",
                     (Json({**AUDIT, "jd_criteria": ["เพศชาย"]}), jid))
        conn.commit()
    res = client.post(f"/api/v1/jobs/{jid}/bias-acknowledgements/preview",
                      json={"acks": [{"phrase": "เพศชาย", "reason": REASON}]})
    assert res.json()["impact"] == []
    assert _score(cid) == 100


def test_ทักษะที่เข้ากฎตายตัวด้วย_ยืนยันแล้วบันทึกเกณฑ์ได้_ถอนต้องลบออก(client, job):
    """AI ชี้ + กฎจับ: ยืนยันแล้วต้องบันทึกเกณฑ์ได้ (เดิม 409 ทั้งที่ยืนยันแล้ว) · ถอนเฉย ๆ ไม่ได้
    เพราะจะเหลือทักษะที่เข้ากฎอยู่ในเกณฑ์โดยไม่มีใครยืนยัน → ถอนพร้อมลบ แล้วคะแนนคิดใหม่."""
    jid, cid = job
    audit = {**AUDIT, "biased_required_skills": [RULE_SKILL]}
    parsed = {"job_title": "x", "min_experience_years": 0, "education": "",
              "required_skills": ["Python", RULE_SKILL], "preferred_skills": []}
    with get_conn() as conn:
        conn.execute("UPDATE jobs SET jd_audit = %s, parsed_criteria = %s WHERE id = %s",
                     (Json(audit), Json(parsed), jid))
        conn.commit()
    assert _put(client, jid, [{"phrase": RULE_SKILL, "reason": REASON}]).status_code == 200
    assert _score(cid) == 50
    res = client.put(f"/api/v1/jobs/{jid}/criteria",
                     json={"required_skills": ["Python", RULE_SKILL], "preferred_skills": ["Docker"]})
    assert res.status_code == 200
    blocked = _put(client, jid, [])
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["stripped_criteria"]["required_skills"] == ["Python"]
    res = client.put(f"/api/v1/jobs/{jid}/bias-acknowledgements", json={"acks": [], "remove_skills": True})
    assert res.status_code == 200
    with get_conn() as conn:
        crit = conn.execute("SELECT parsed_criteria FROM jobs WHERE id = %s", (jid,)).fetchone()
    assert crit["parsed_criteria"]["required_skills"] == ["Python"]


def test_removal_phrases_เอาเฉพาะตัวเลือกที่เข้ากฎในกลุ่ม():
    from app.bias_ack import removal_phrases, strip_skills
    blocked = [{"skill": f"{RULE_SKILL} | สถาบันใดก็ได้", "side": "required", "phrase": None}]
    phrases = removal_phrases(blocked)
    assert phrases == [RULE_SKILL]
    assert strip_skills([f"{RULE_SKILL} | สถาบันใดก็ได้"], [], phrases)["required_skills"] == ["สถาบันใดก็ได้"]
