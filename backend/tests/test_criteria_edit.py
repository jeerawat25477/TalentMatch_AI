"""HR แก้รายการทักษะของตำแหน่งงาน แล้วคำนวณคะแนนคนเดิมใหม่ (app/criteria_edit.py).

รัน: docker compose exec backend python -m pytest tests/test_criteria_edit.py -v

ที่มา: memory-bank/06_scoring_criteria.md — AI ดึง "A, B, or C" เป็นข้อบังคับทุกตัว และเอา
หน้าที่งานมาเป็นทักษะ คนที่ตรงคุณสมบัติครบอาจถูกปฏิเสธอัตโนมัติ

สิ่งที่เทสชุดนี้กัน:
1. **สูตรเดียว** — คะแนนที่คำนวณใหม่ต้องมาจาก matcher.evaluate_skills ตัวเดียวกับกราฟ
2. **ไม่ทำอะไรเองนอกจากคะแนน** — ไม่แตะร่างอีเมล คำถาม คำตัดสินของ HR
3. **พรีวิวไม่เขียน DB** และบันทึกถูกกันไว้เมื่อกราฟกำลังเดิน/รอคิว
4. **ป้ายตรวจอีกครั้ง** ขึ้นเฉพาะคนที่แบนด์เปลี่ยน และหายเมื่อ HR ตัดสินใหม่
5. **กราฟใช้เกณฑ์ใหม่** เมื่อ HR อนุมัติทีหลัง ไม่ใช่เกณฑ์เก่าที่ค้างใน checkpoint
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from psycopg.types.json import Json

from app.agents import runner
from app.agents.graph import build_graph
from app.agents.models import EmailDraft, InterviewPlan
from app.agents.nodes import bias_auditor, drafter, jd_analyzer, planner, resume_parser
from app.agents.nodes.matcher import evaluate_skills, match_candidates
from app.auth import get_current_user
from app.criteria_edit import (
    BLOATED_REQUIRED,
    criteria_warnings,
    needs_recheck,
    normalize_criteria,
)
from app.database import get_conn
from app.main import app

NOW = datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)


# ---------- ฟังก์ชันบริสุทธิ์ ----------


class TestEvaluateSkillsIsTheGraphFormula:
    def test_ผลเท่ากับ_match_candidates_ทุกฟิลด์(self):
        """ถ้าวันไหนสองทางนี้ต่างกัน คนเดิมที่ถูกคำนวณใหม่กับคนใหม่จะได้คะแนนคนละแบบ."""
        profile = {
            "candidate_id": "c1",
            "skills": ["Python", "PostgreSQL", "Docker"],
            "skill_evidence": {"Python": "ใช้ Python 5 ปี"},
        }
        text = "x" * 3000
        state = {
            "raw_jd": "",
            "raw_resumes": [{"candidate_id": "c1", "filename": "", "content": text}],
            "analyzed_jd": {"required_skills": ["Python", "SQL", "Go"], "preferred_skills": ["Docker", "K8s"]},
            "parsed_resumes": [profile],
            "evaluations": [],
            "bias_revision_count": {},
            "bias_revision_pending": {},
            "bias_exclusions": {},
        }
        graph_eval = match_candidates(state)["evaluations"][0]
        direct = evaluate_skills(["Python", "SQL", "Go"], ["Docker", "K8s"], profile, text)
        for key in ("fit_score", "gaps", "score_explanation", "skill_evidence", "confidence"):
            assert graph_eval[key] == direct[key], key

    def test_เกณฑ์ที่ลูปอคติตัดไว้ยังถูกตัดต่อ(self):
        profile = {"skills": ["Python"]}
        with_ex = evaluate_skills(["Python", "Java"], [], profile, "x", {"required_skills": ["Java"]})
        assert with_ex["gaps"]["missing_required"] == []
        assert with_ex["fit_score"] == 100


class TestNormalize:
    def test_ตัดช่องว่างและช่องว่างเปล่า(self):
        r = normalize_criteria(["  Python ", "", "   "], [])
        assert r["required_skills"] == ["Python"]

    def test_ซ้ำด้วยชื่อมาตรฐานในฝั่งเดียวกัน(self):
        r = normalize_criteria(["Node.js", "NodeJs"], [])
        assert r["required_skills"] == ["Node.js"]

    def test_ซ้ำข้ามฝั่ง_ฝั่งที่ต้องมีชนะ(self):
        r = normalize_criteria(["Docker"], ["docker", "Git"])
        assert r["required_skills"] == ["Docker"]
        assert r["preferred_skills"] == ["Git"]

    def test_คำที่ไม่ใช่ทักษะถูกคัดออกและแจ้งกลับ(self):
        """matcher ไม่นับคำพวกนี้อยู่แล้ว ถ้าทิ้งเงียบ HR จะเห็นชิปที่ไม่ได้ถูกนับ."""
        r = normalize_criteria(["Python", "product owners"], [])
        assert r["required_skills"] == ["Python"]
        assert r["dropped"] == ["product owners"]


class TestWarnings:
    def test_มีแค่ทักษะที่อยากได้(self):
        assert any("มีแค่ทักษะที่อยากได้" in w for w in criteria_warnings([], ["Git"]))

    def test_ไม่มีทักษะเลย(self):
        assert any("ไม่มีทักษะเลย" in w for w in criteria_warnings([], []))

    def test_ทักษะที่ต้องมีพอง(self):
        many = [f"s{i}" for i in range(BLOATED_REQUIRED + 1)]
        assert any("ข้อบังคับ" in w for w in criteria_warnings(many, ["Git"]))

    def test_ปกติไม่มีคำเตือน(self):
        assert criteria_warnings(["Python"], ["Git"]) == []


class TestNeedsRecheck:
    def test_ไม่เคยคำนวณใหม่(self):
        assert needs_recheck(None, None, 60, None) is False

    def test_แบนด์เดิมไม่ต้องตรวจ(self):
        """55 → 62 ยังรอ HR เหมือนเดิม เส้นทางที่กราฟเดินไปแล้วยังถูก."""
        assert needs_recheck(NOW, 55, 62, None) is False

    def test_แบนด์เปลี่ยนและยังไม่ตัดสินใหม่(self):
        assert needs_recheck(NOW, 28, 80, None) is True
        assert needs_recheck(NOW, 28, 80, NOW - timedelta(days=1)) is True

    def test_HR_ตัดสินใหม่หลังคำนวณแล้วป้ายหาย(self):
        assert needs_recheck(NOW, 28, 80, NOW + timedelta(minutes=5)) is False


# ---------- endpoint (DB จริง · ไม่เรียก LLM) ----------


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: "admin-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


AI_CRITERIA = {
    "job_title": "AI Engineer (ทดสอบ)",
    "min_experience_years": 2,
    "education": "ป.ตรี",
    # แบบที่ AI ดึงผิด: "or" กลายเป็นข้อบังคับทุกตัว
    "required_skills": ["Python", "PyTorch", "TensorFlow", "Scikit-learn", "Hugging Face"],
    "preferred_skills": [],
}


@pytest.fixture
def job():
    """ตำแหน่ง + ผู้สมัคร 2 คน (รู้ PyTorch ตัวเดียว / ไม่ตรงเลย) พร้อมผลประเมินเกณฑ์เก่า."""
    with get_conn() as conn:
        j = conn.execute(
            "INSERT INTO jobs (title, raw_text, parsed_criteria) VALUES (%s, %s, %s) RETURNING id",
            ("AI Engineer (ทดสอบแก้เกณฑ์ — ลบได้)", "Python and PyTorch, TensorFlow, or Hugging Face",
             Json(AI_CRITERIA)),
        ).fetchone()
        ids = []
        for name, skills in (("ตรงครบจริง", ["Python", "PyTorch"]), ("ไม่ตรงเลย", ["Photoshop"])):
            c = conn.execute(
                """INSERT INTO candidates (job_id, full_name, raw_resume_text, parsed_resume)
                   VALUES (%s, %s, %s, %s) RETURNING id""",
                (j["id"], name, "x" * 3000, Json({"skills": skills})),
            ).fetchone()
            r = evaluate_skills(AI_CRITERIA["required_skills"], [], {"skills": skills}, "x" * 3000)
            conn.execute(
                """INSERT INTO evaluations (job_id, candidate_id, fit_score, gap_analysis,
                       interview_plan, email_draft)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (j["id"], c["id"], r["fit_score"], Json(r["gaps"]),
                 Json({"questions": [{"question": "เดิม", "expected_answer": ""}]}),
                 Json({"kind": "rejection", "subject": "เดิม", "body": "เดิม"})),
            )
            ids.append(str(c["id"]))
        conn.commit()
    yield str(j["id"]), ids
    with get_conn() as conn:
        conn.execute("DELETE FROM processing_queue WHERE candidate_id = ANY(%s::uuid[])", (ids,))
        conn.execute("DELETE FROM candidates WHERE job_id = %s", (j["id"],))
        conn.execute("DELETE FROM jobs WHERE id = %s", (j["id"],))
        conn.commit()


FIXED = {"required_skills": ["Python", "PyTorch"], "preferred_skills": []}


def _eval(cid):
    with get_conn() as conn:
        return conn.execute(
            """SELECT fit_score, gap_analysis, interview_plan, email_draft,
                      rescored_from, rescored_at FROM evaluations WHERE candidate_id = %s""",
            (cid,),
        ).fetchone()


def _job(jid):
    with get_conn() as conn:
        return conn.execute(
            "SELECT parsed_criteria, ai_criteria, criteria_edited_at FROM jobs WHERE id = %s", (jid,)
        ).fetchone()


class TestPreview:
    def test_พรีวิวบอกผลกระทบโดยไม่เขียนอะไร(self, client, job):
        jid, (strong, weak) = job
        before = _eval(strong)
        r = client.post(f"/api/v1/jobs/{jid}/criteria/preview", json=FIXED)
        assert r.status_code == 200, r.text
        row = next(i for i in r.json()["impact"] if i["candidate_id"] == strong)
        # เกณฑ์เก่า: ตรง 2/5 = 40 → ปฏิเสธ · เกณฑ์ที่ถูก: ตรง 2/2 = 100 → ผ่าน
        assert (row["old_score"], row["new_score"]) == (40, 100)
        assert (row["old_band"], row["new_band"]) == ("fail", "pass")
        assert _eval(strong) == before
        assert _job(jid)["criteria_edited_at"] is None

    def test_แจ้งคำที่ถูกคัดออกและคำเตือน(self, client, job):
        jid, _ = job
        r = client.post(
            f"/api/v1/jobs/{jid}/criteria/preview",
            json={"required_skills": [], "preferred_skills": ["Git", "product owners"]},
        ).json()
        assert r["dropped"] == ["product owners"]
        assert any("มีแค่ทักษะที่อยากได้" in w for w in r["warnings"])

    def test_ต้องล็อกอินก่อน(self, job):
        jid, _ = job
        assert TestClient(app).post(f"/api/v1/jobs/{jid}/criteria/preview", json=FIXED).status_code == 401

    def test_ไม่พบตำแหน่ง(self, client):
        r = client.post("/api/v1/jobs/00000000-0000-0000-0000-000000000000/criteria/preview", json=FIXED)
        assert r.status_code == 404

    def test_ชื่อทักษะยาวเกินได้_422(self, client, job):
        jid, _ = job
        r = client.post(f"/api/v1/jobs/{jid}/criteria/preview",
                        json={"required_skills": ["x" * 101], "preferred_skills": []})
        assert r.status_code == 422


class TestSave:
    def test_บันทึกแล้วคำนวณใหม่เฉพาะคะแนน(self, client, job):
        """ร่างอีเมลปฏิเสธและคำถามเดิมต้องยังอยู่ — HR เป็นคนตัดสินต่อเอง."""
        jid, (strong, weak) = job
        r = client.put(f"/api/v1/jobs/{jid}/criteria", json=FIXED)
        assert r.status_code == 200, r.text
        e = _eval(strong)
        assert e["fit_score"] == 100
        assert e["gap_analysis"]["missing_required"] == []
        assert e["rescored_from"] == 40 and e["rescored_at"] is not None
        assert e["email_draft"]["kind"] == "rejection"
        assert e["interview_plan"]["questions"][0]["question"] == "เดิม"
        # คนที่คะแนนไม่เปลี่ยน (0 → 0) ไม่มีร่องรอย
        assert _eval(weak)["rescored_from"] is None

    def test_คงข้อมูลอื่นของเกณฑ์และเก็บของ_AI_ไว้ครั้งแรกเท่านั้น(self, client, job):
        jid, _ = job
        client.put(f"/api/v1/jobs/{jid}/criteria", json=FIXED)
        client.put(f"/api/v1/jobs/{jid}/criteria", json={"required_skills": ["Python"], "preferred_skills": []})
        j = _job(jid)
        assert j["ai_criteria"]["required_skills"] == AI_CRITERIA["required_skills"]
        assert j["parsed_criteria"]["required_skills"] == ["Python"]
        assert j["parsed_criteria"]["min_experience_years"] == 2
        assert j["parsed_criteria"]["education"] == "ป.ตรี"

    def test_แก้หลายรอบ_rescored_from_ยังเป็นคะแนนตอนที่มีคนตัดสินจริง(self, client, job):
        jid, (strong, _) = job
        client.put(f"/api/v1/jobs/{jid}/criteria", json=FIXED)  # 40 → 100
        client.put(f"/api/v1/jobs/{jid}/criteria",
                   json={"required_skills": ["Python", "PyTorch", "Go"], "preferred_skills": []})  # → 67
        e = _eval(strong)
        assert e["fit_score"] == 67
        assert e["rescored_from"] == 40

    def test_ไม่แตะคำตัดสินของ_HR(self, client, job):
        jid, (strong, _) = job
        with get_conn() as conn:
            conn.execute("INSERT INTO hr_decisions (candidate_id, decision, notes) VALUES (%s, 'rejected', 'ตามเกณฑ์เดิม')", (strong,))
            conn.commit()
        client.put(f"/api/v1/jobs/{jid}/criteria", json=FIXED)
        with get_conn() as conn:
            d = conn.execute("SELECT decision, notes FROM hr_decisions WHERE candidate_id = %s", (strong,)).fetchone()
        assert (d["decision"], d["notes"]) == ("rejected", "ตามเกณฑ์เดิม")

    def test_ป้ายตรวจอีกครั้งขึ้นในหน้ารายชื่อและรายละเอียด(self, client, job):
        jid, (strong, weak) = job
        client.put(f"/api/v1/jobs/{jid}/criteria", json=FIXED)
        rows = {c["id"]: c for c in client.get(f"/api/v1/jobs/{jid}/candidates").json()}
        assert rows[strong]["needs_recheck"] is True and rows[strong]["rescored_from"] == 40
        assert rows[weak]["needs_recheck"] is False
        assert client.get(f"/api/v1/candidates/{strong}").json()["needs_recheck"] is True

    def test_กราฟกำลังเดินอยู่ได้_409(self, client, job):
        jid, (strong, _) = job
        runner.reserve_candidates([strong])
        try:
            r = client.put(f"/api/v1/jobs/{jid}/criteria", json=FIXED)
        finally:
            runner.release_candidate(strong)
        assert r.status_code == 409
        assert _job(jid)["criteria_edited_at"] is None

    def test_มีงานค้างในคิวได้_409(self, client, job):
        """ใช้สถานะ deferred_quota ที่เพิ่งพัก — worker ยังไม่หยิบใหม่ จึงไม่มีทางเรียก LLM."""
        jid, (strong, _) = job
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO processing_queue (candidate_id, job_id, kind, status)
                   VALUES (%s, %s, 'process', 'deferred_quota')""",
                (strong, jid),
            )
            conn.commit()
        assert client.put(f"/api/v1/jobs/{jid}/criteria", json=FIXED).status_code == 409

    def test_คืนค่าตามที่_AI_ดึง(self, client, job):
        jid, (strong, _) = job
        client.put(f"/api/v1/jobs/{jid}/criteria", json=FIXED)
        r = client.post(f"/api/v1/jobs/{jid}/criteria/reset")
        assert r.status_code == 200, r.text
        j = _job(jid)
        assert j["parsed_criteria"]["required_skills"] == AI_CRITERIA["required_skills"]
        assert j["criteria_edited_at"] is None
        assert _eval(strong)["fit_score"] == 40

    def test_คืนค่าตอนยังไม่เคยแก้ได้_409(self, client, job):
        jid, _ = job
        assert client.post(f"/api/v1/jobs/{jid}/criteria/reset").status_code == 409


# ---------- กราฟใช้เกณฑ์ใหม่เมื่อ HR ตัดสินทีหลัง ----------


class TestGraphUsesNewCriteria:
    def test_อนุมัติหลังแก้เกณฑ์_planner_เห็นทักษะที่ขาดตามเกณฑ์ใหม่(self, client, job, monkeypatch):
        """checkpoint ยังถือ gaps ของเกณฑ์เก่า ถ้าไม่เติมจาก DB planner จะถามเรื่องที่ HR ตัดออกไปแล้ว."""
        jid, (strong, _) = job
        g = build_graph().compile(checkpointer=InMemorySaver(), interrupt_before=["interview_planner"])
        monkeypatch.setattr(runner, "get_graph", lambda: g)
        prompts: list[str] = []
        monkeypatch.setattr(planner, "structured_invoke",
                            lambda p, m: prompts.append(p) or InterviewPlan(questions=[]))
        monkeypatch.setattr(drafter, "structured_invoke",
                            lambda p, m: EmailDraft(kind="invitation", subject="s", body="b"))
        for mod in (resume_parser, bias_auditor, jd_analyzer):
            monkeypatch.setattr(mod, "structured_invoke",
                                lambda *a, **k: (_ for _ in ()).throw(AssertionError("รันจากต้น")))

        # checkpoint แบบเกณฑ์เก่า: ขาด TensorFlow / Scikit-learn / Hugging Face
        old_gaps = {"matched_required": ["Python", "PyTorch"],
                    "missing_required": ["TensorFlow", "Scikit-learn", "Hugging Face"],
                    "matched_preferred": [], "missing_preferred": []}
        g.update_state(runner._config(strong), {
            "raw_jd": "", "analyzed_jd": AI_CRITERIA,
            "raw_resumes": [{"candidate_id": strong, "filename": "", "content": "x"}],
            "parsed_resumes": [{"full_name": "ตรงครบจริง"}],
            "evaluations": [{"candidate_id": strong, "fit_score": 60, "audit_status": "passed",
                             "audit_log": "", "gaps": old_gaps}],
            "hr_decision": {}, "hr_notes": {}, "interview_plans": {}, "email_drafts": {},
            "similar_candidates": {}, "bias_revision_count": {}, "bias_revision_pending": {},
            "bias_exclusions": {},
        }, as_node="bias_auditor")

        client.put(f"/api/v1/jobs/{jid}/criteria", json=FIXED)
        runner.resume_after_decision(strong, "approved", "")

        assert prompts, "planner ต้องถูกเรียก"
        assert "TensorFlow" not in prompts[0]
        values = g.get_state(runner._config(strong)).values
        assert values["analyzed_jd"]["required_skills"] == FIXED["required_skills"]
        assert values["evaluations"][0]["fit_score"] == 100
        assert values["evaluations"][0]["audit_status"] == "passed"  # ฟิลด์อื่นคงเดิม
