"""กราฟที่หยุดกลางทางต้องไม่ทำให้งานที่จ่ายโควตาไปแล้วหาย และต้องเดินต่อ ไม่ใช่รันใหม่.

รัน: docker compose exec backend python -m pytest tests/test_graph_recovery.py -v

ที่มา: ผู้สมัครที่ HR อนุมัติแล้ว planner สร้างคำถามเสร็จ แต่ email_drafter ล้มเพราะโควตา —
คำถามค้างอยู่ใน checkpoint ไม่เคยถึงหน้าเว็บ สถานะถูกรายงานว่า "รอ HR" และไม่มีทางสั่งทำต่อ

สิ่งที่เทสชุดนี้กัน:
1. **คำถามต้องถูกบันทึกทันทีที่ planner เสร็จ** ไม่รอจนกราฟเดินจบ
2. **ลองใหม่ต้องเดินต่อจากโหนดที่ค้าง** — planner ต้องไม่ถูกเรียกซ้ำ
3. **งาน process ที่ลองใหม่ต้องไม่รันจากต้น** ไม่เรียก parser/auditor ซ้ำ และไม่ลบแถว
   evaluations เดิม (invoke ข้อมูลตั้งต้นบน thread ที่มี checkpoint = LangGraph เริ่มใหม่)
4. **สถานะ "ค้างกลางทาง" ต้องแยกจาก "รอ HR"** และเส้นคะแนนมาจาก bands.py
5. endpoint ทำต่อ: ด่านครบ และเลือก kind ถูกตามว่ามีคำตัดสินหรือไม่

ใช้กราฟจริงจาก build_graph() แต่ checkpointer ในหน่วยความจำ และ mock LLM ทุกโหนด —
ไม่กินโควตา ไม่เขียน checkpoint ลง Postgres
"""
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app.agents import bands, runner
from app.agents.graph import build_graph
from app.agents.models import EmailDraft, InterviewPlan
from app.agents.nodes import drafter, jd_analyzer, planner, resume_parser
from app.agents.runner import _resume_point, resolve_graph_status
from app.auth import get_current_user
from app.database import get_conn
from app.main import app
from app.routers import candidates as candidates_router

REVIEW_SCORE = 60  # ช่วงรอ HR
PASS_SCORE = 85    # ผ่านอัตโนมัติ
FAIL_SCORE = 20

QUESTIONS = [{"question": "เล่างาน FastAPI ที่ภูมิใจ", "expected_answer": "บทบาทของตัวเอง"}]


# ---------- สถานะกราฟ (ฟังก์ชันบริสุทธิ์) ----------


class TestResolveGraphStatus:
    def test_ไม่มี_checkpoint_คือกำลังประมวลผล(self):
        assert resolve_graph_status(False, (), None, None) == "processing"

    def test_เดินจบแล้วคือเสร็จ(self):
        assert resolve_graph_status(True, (), "approved", REVIEW_SCORE) == "completed"

    def test_พักที่_interrupt_ไม่มีคำตัดสิน_คะแนนช่วงรอคือรอ_HR(self):
        assert resolve_graph_status(True, ("interview_planner",), None, REVIEW_SCORE) == "awaiting_hr"
        assert resolve_graph_status(True, ("interview_planner",), "pending", REVIEW_SCORE) == "awaiting_hr"

    def test_อนุมัติแล้วแต่ค้างที่_drafter_คือค้างกลางทาง(self):
        """เคสที่เกิดจริง — เดิมถูกรายงานว่ารอ HR ทั้งที่ HR ตัดสินไปแล้ว."""
        assert resolve_graph_status(True, ("email_drafter",), "approved", REVIEW_SCORE) == "interrupted"

    def test_ตัดสินแล้วแต่ยังค้างที่_interrupt_คือค้างกลางทาง(self):
        assert resolve_graph_status(True, ("interview_planner",), "approved", REVIEW_SCORE) == "interrupted"
        assert resolve_graph_status(True, ("interview_planner",), "rejected", REVIEW_SCORE) == "interrupted"

    def test_คะแนนผ่านอัตโนมัติแต่ค้างที่_interrupt_คือค้างกลางทาง(self):
        """auto-advance ล้ม — ถ้าบอกว่ารอ HR คนคะแนนสูงจะดูเหมือนต้องให้คนตัดสิน."""
        assert resolve_graph_status(True, ("interview_planner",), None, PASS_SCORE) == "interrupted"

    def test_เส้นคะแนนมาจาก_bands_ไม่ใช่ฮาร์ดโค้ด(self, monkeypatch):
        assert resolve_graph_status(True, ("interview_planner",), None, REVIEW_SCORE) == "awaiting_hr"
        monkeypatch.setattr(bands, "AUTO_ADVANCE_ABOVE", REVIEW_SCORE - 1)
        assert resolve_graph_status(True, ("interview_planner",), None, REVIEW_SCORE) == "interrupted"


class TestResumePoint:
    def test_ไม่มี_checkpoint_เริ่มใหม่(self):
        assert _resume_point(False, ()) == "fresh"

    @pytest.mark.parametrize("nxt", [(), ("interview_planner",), ("email_drafter",)])
    def test_คัดกรองเสร็จแล้วข้ามไปช่วงหลัง(self, nxt):
        assert _resume_point(True, nxt) == "after_screening"

    @pytest.mark.parametrize("nxt", [("resume_parser",), ("bias_auditor",), ("matcher",)])
    def test_ค้างกลางช่วงคัดกรองเดินต่อจากโหนดที่ล้ม(self, nxt):
        assert _resume_point(True, nxt) == "resume_screening"


class TestEffectiveGraphStatus:
    def test_กำลังรันหรือรอคิวอยู่ไม่ขึ้นว่าค้าง(self):
        """checkpoint บันทึกทุกขั้น ระหว่างเดินจึงดูเหมือนค้าง — ห้ามโชว์ปุ่มทำต่อให้กดซ้ำ."""
        f = candidates_router._effective_graph_status
        assert f("interrupted", "c1", frozenset({"c1"}), None) == "processing"
        assert f("interrupted", "c1", frozenset(), "queued") == "processing"
        assert f("interrupted", "c1", frozenset(), None) == "interrupted"
        assert f("awaiting_hr", "c1", frozenset({"c1"}), None) == "awaiting_hr"


# ---------- กราฟจริง + checkpointer ในหน่วยความจำ + DB จริง ----------


@pytest.fixture
def cand():
    """งาน + ผู้สมัคร + แถว evaluations ของตัวเอง แล้วลบทิ้ง."""
    with get_conn() as conn:
        job = conn.execute(
            "INSERT INTO jobs (title, raw_text) VALUES (%s, %s) RETURNING id",
            ("เทสกู้กราฟค้าง (ลบได้)", "ต้องมี Python"),
        ).fetchone()
        c = conn.execute(
            """INSERT INTO candidates (job_id, full_name, raw_resume_text)
               VALUES (%s, %s, %s) RETURNING id""",
            (job["id"], "ผู้สมัครกราฟค้าง", "Python FastAPI " * 20),
        ).fetchone()
        conn.commit()
    yield str(job["id"]), str(c["id"])
    with get_conn() as conn:
        conn.execute("DELETE FROM processing_queue WHERE candidate_id = %s", (c["id"],))
        conn.execute("DELETE FROM candidates WHERE id = %s", (c["id"],))
        conn.execute("DELETE FROM jobs WHERE id = %s", (job["id"],))
        conn.commit()
    runner.release_candidate(str(c["id"]))


def _add_evaluation(job_id: str, cid: str, score: int) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO evaluations (job_id, candidate_id, fit_score, email_sent_at)
               VALUES (%s, %s, %s, now())""",
            (job_id, cid, score),
        )
        conn.commit()


def _eval_row(cid: str) -> dict:
    with get_conn() as conn:
        return conn.execute(
            """SELECT interview_plan, email_draft, email_sent_at, created_at
                 FROM evaluations WHERE candidate_id = %s""",
            (cid,),
        ).fetchone()


@pytest.fixture
def graph(monkeypatch):
    """กราฟจริงแต่ checkpoint อยู่ในหน่วยความจำ — ไม่แตะตาราง checkpoint ของระบบจริง."""
    g = build_graph().compile(
        checkpointer=InMemorySaver(), interrupt_before=["interview_planner"]
    )
    monkeypatch.setattr(runner, "get_graph", lambda: g)
    return g


@pytest.fixture
def llm(monkeypatch):
    """นับการเรียก LLM ต่อโหนด · โหนดช่วงคัดกรองถูกเรียกเมื่อไรคือพัง (แปลว่ารันใหม่จากต้น)."""
    calls = {"planner": 0, "drafter": 0}
    fail = {"drafter": 0, "planner": 0}  # จำนวนครั้งที่ต้องล้มก่อนจะสำเร็จ

    def fake_planner(prompt, model):
        calls["planner"] += 1
        if fail["planner"] > 0:
            fail["planner"] -= 1
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
        return InterviewPlan(questions=QUESTIONS)

    def fake_drafter(prompt, model):
        calls["drafter"] += 1
        if fail["drafter"] > 0:
            fail["drafter"] -= 1
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
        kind = "rejection" if "ยังไม่ผ่าน" in prompt else "invitation"
        return EmailDraft(kind=kind, subject="s", body="b")

    def forbidden(*a, **kw):
        raise AssertionError("โหนดช่วงคัดกรองถูกเรียกซ้ำ = กราฟถูกรันใหม่จากต้น")

    monkeypatch.setattr(planner, "structured_invoke", fake_planner)
    monkeypatch.setattr(drafter, "structured_invoke", fake_drafter)
    # bias_auditor ไม่เรียก LLM แล้ว (อ่าน jobs.jd_audit) จึงไม่ต้องกันที่นี่
    for mod in (resume_parser, jd_analyzer):
        monkeypatch.setattr(mod, "structured_invoke", forbidden)
    monkeypatch.setattr(runner, "index_candidate", lambda *a, **kw: None)
    return calls, fail


def _seed_after_audit(graph, cid: str, score: int, decision: str | None = None) -> None:
    """ตั้ง state ให้เหมือนเพิ่งจบ bias_auditor — router ตัดสินต่อเองตามปกติ."""
    state = {
        "raw_jd": "ต้องมี Python",
        "analyzed_jd": {"job_title": "Backend Developer"},
        "raw_resumes": [{"candidate_id": cid, "filename": "", "content": "x"}],
        "parsed_resumes": [{"full_name": "ผู้สมัครกราฟค้าง", "email": None}],
        "evaluations": [{
            "candidate_id": cid, "fit_score": score, "audit_status": "passed",
            "audit_log": "", "gaps": {"matched_required": ["Python"]},
        }],
        "hr_decision": {cid: decision} if decision else {},
        "hr_notes": {},
        "interview_plans": {},
        "email_drafts": {},
        "similar_candidates": {},
        "bias_revision_count": {},
        "bias_revision_pending": {},
        "bias_exclusions": {},
    }
    graph.update_state(runner._config(cid), state, as_node="bias_auditor")


class TestPlanPersistedBeforeDrafter:
    def test_drafter_ล้มแล้วคำถามต้องอยู่ใน_db_แล้ว(self, cand, graph, llm):
        job_id, cid = cand
        calls, fail = llm
        _add_evaluation(job_id, cid, REVIEW_SCORE)
        _seed_after_audit(graph, cid, REVIEW_SCORE)
        fail["drafter"] = 1

        with pytest.raises(RuntimeError):
            # exception ต้องยังหลุดออกไป — คิวต้องรู้ว่าล้มเพื่อลองใหม่
            runner.resume_after_decision(cid, "approved", "")

        row = _eval_row(cid)
        assert row["interview_plan"]["questions"] == QUESTIONS
        assert row["email_draft"] is None
        assert graph.get_state(runner._config(cid)).next == ("email_drafter",)

    def test_ลองใหม่เดินต่อที่_drafter_ไม่เรียก_planner_ซ้ำ(self, cand, graph, llm):
        job_id, cid = cand
        calls, fail = llm
        _add_evaluation(job_id, cid, REVIEW_SCORE)
        _seed_after_audit(graph, cid, REVIEW_SCORE)
        fail["drafter"] = 1
        with pytest.raises(RuntimeError):
            runner.resume_after_decision(cid, "approved", "")

        runner.resume_after_decision(cid, "approved", "")

        assert calls == {"planner": 1, "drafter": 2}
        row = _eval_row(cid)
        assert row["interview_plan"]["questions"] == QUESTIONS
        assert row["email_draft"]["kind"] == "invitation"
        assert graph.get_state(runner._config(cid)).next == ()

    def test_ปฏิเสธไม่บันทึกแผนว่างกลางทาง_และท้ายรอบไม่มีคำถาม(self, cand, graph, llm):
        job_id, cid = cand
        calls, _ = llm
        _add_evaluation(job_id, cid, FAIL_SCORE)
        _seed_after_audit(graph, cid, FAIL_SCORE)

        runner.resume_after_decision(cid, "rejected", "")

        assert calls["planner"] == 0
        row = _eval_row(cid)
        assert row["interview_plan"] is None
        assert row["email_draft"]["kind"] == "rejection"


class TestRetryAfterRewind:
    def test_ย้อนแล้ว_planner_ล้ม_ลองใหม่ต้องรันจริงไม่ใช่จบเงียบ(self, cand, graph, llm):
        """เดิม update_state ไม่ระบุ as_node — checkpoint ล่าสุดเกิดจาก update_state รอบก่อน
        LangGraph จึงเดาผิดจน next ว่าง คิวนับว่าสำเร็จทั้งที่ไม่ได้สร้างคำถามหรืออีเมลเลย."""
        job_id, cid = cand
        calls, fail = llm
        _add_evaluation(job_id, cid, FAIL_SCORE)
        _seed_after_audit(graph, cid, FAIL_SCORE)
        runner.resume_after_decision(cid, "rejected", "")  # จบด้วยอีเมลปฏิเสธ
        fail["planner"] = 1

        with pytest.raises(RuntimeError):
            runner.resume_after_decision(cid, "approved", "")  # กลับคำ → ย้อน → planner ล้ม
        runner.resume_after_decision(cid, "approved", "")

        assert calls["planner"] == 2
        row = _eval_row(cid)
        assert row["interview_plan"]["questions"] == QUESTIONS
        assert row["email_draft"]["kind"] == "invitation"
        assert graph.get_state(runner._config(cid)).next == ()


class TestProcessRetryDoesNotRestart:
    def test_auto_advance_ล้มแล้วลองใหม่ต้องเดินต่อ_ไม่ลบแถวเดิม(self, cand, graph, llm):
        """เดิมคิวเรียก process_candidate ซ้ำ → invoke(ข้อมูลตั้งต้น) → รันจากต้น
        จ่าย parser/auditor ซ้ำ และลบแถว evaluations ทิ้งพร้อม email_sent_at."""
        job_id, cid = cand
        calls, fail = llm
        _add_evaluation(job_id, cid, PASS_SCORE)
        before = _eval_row(cid)
        _seed_after_audit(graph, cid, PASS_SCORE)
        fail["planner"] = 1

        with pytest.raises(RuntimeError):
            runner.process_candidate(job_id, cid, "ต้องมี Python", {}, "x")
        runner.process_candidate(job_id, cid, "ต้องมี Python", {}, "x")

        # forbidden fixture จะโยน AssertionError ถ้า parser/auditor ถูกเรียก
        assert calls == {"planner": 2, "drafter": 1}
        after = _eval_row(cid)
        assert after["created_at"] == before["created_at"]
        assert after["email_sent_at"] == before["email_sent_at"]
        assert after["interview_plan"]["questions"] == QUESTIONS
        assert after["email_draft"]["kind"] == "invitation"

    def test_ค้างที่_drafter_แล้ว_process_เดินต่อได้(self, cand, graph, llm):
        job_id, cid = cand
        calls, fail = llm
        _add_evaluation(job_id, cid, PASS_SCORE)
        _seed_after_audit(graph, cid, PASS_SCORE)
        fail["drafter"] = 1
        with pytest.raises(RuntimeError):
            runner.process_candidate(job_id, cid, "ต้องมี Python", {}, "x")
        assert _eval_row(cid)["interview_plan"]["questions"] == QUESTIONS

        runner.process_candidate(job_id, cid, "ต้องมี Python", {}, "x")
        assert calls == {"planner": 1, "drafter": 2}
        assert _eval_row(cid)["email_draft"]["kind"] == "invitation"


# ---------- endpoint ทำต่อ ----------
# ⚠️ ไม่ insert แถวคิวจริง: worker ใน backend กำลังทำงานอยู่ ถ้าหยิบแถวของเทสไปได้
# มันจะรันกราฟจริงและเรียก Gemini จริง — จับการ enqueue ไว้แทน


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: "admin-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def enqueued(monkeypatch) -> list:
    got: list = []
    monkeypatch.setattr(
        candidates_router, "enqueue",
        lambda cid, job_id, kind, payload=None: got.append((kind, payload)),
    )
    monkeypatch.setattr(candidates_router, "pending_status", lambda cid: None)
    return got


def _status_is(monkeypatch, status: str) -> None:
    monkeypatch.setattr(candidates_router, "get_graph_status", lambda *a, **kw: status)


class TestResumeEndpoint:
    def test_ต้องล็อกอินก่อน(self, cand):
        _, cid = cand
        assert TestClient(app).post(f"/api/v1/candidates/{cid}/resume").status_code == 401

    def test_ไม่พบผู้สมัครได้_404(self, client, enqueued):
        r = client.post("/api/v1/candidates/00000000-0000-0000-0000-000000000000/resume")
        assert r.status_code == 404

    @pytest.mark.parametrize("status", ["awaiting_hr", "completed", "processing"])
    def test_ไม่ได้ค้างกลางทางได้_409(self, client, cand, enqueued, monkeypatch, status):
        _, cid = cand
        _status_is(monkeypatch, status)
        assert client.post(f"/api/v1/candidates/{cid}/resume").status_code == 409
        assert enqueued == []

    def test_กำลังรันอยู่ได้_409(self, client, cand, enqueued, monkeypatch):
        _, cid = cand
        _status_is(monkeypatch, "interrupted")
        runner.reserve_candidates([cid])
        assert client.post(f"/api/v1/candidates/{cid}/resume").status_code == 409
        assert enqueued == []

    def test_มีงานในคิวแล้วได้_409(self, client, cand, enqueued, monkeypatch):
        """ทะเบียนในโปรเซสหายตอนรีสตาร์ต แต่แถวคิวไม่หาย — ต้องเช็คทั้งสองอย่าง."""
        _, cid = cand
        _status_is(monkeypatch, "interrupted")
        monkeypatch.setattr(candidates_router, "pending_status", lambda c: "queued")
        assert client.post(f"/api/v1/candidates/{cid}/resume").status_code == 409
        assert enqueued == []

    def test_มีคำตัดสินแล้วเข้าคิวเป็น_resume_after_decision(self, client, cand, enqueued, monkeypatch):
        """ต้องส่งคำตัดสินเดิมจาก DB ไป ไม่ใช่เดาจากคะแนน — HR มีอำนาจสูงสุด."""
        job_id, cid = cand
        _add_evaluation(job_id, cid, REVIEW_SCORE)
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO hr_decisions (candidate_id, decision, notes) VALUES (%s, 'approved', 'ok')",
                (cid,),
            )
            conn.commit()
        _status_is(monkeypatch, "interrupted")

        assert client.post(f"/api/v1/candidates/{cid}/resume").status_code == 202
        assert enqueued == [("resume_after_decision", {"decision": "approved", "notes": "ok"})]

    def test_ไม่มีคำตัดสินเข้าคิวเป็น_process(self, client, cand, enqueued, monkeypatch):
        job_id, cid = cand
        _add_evaluation(job_id, cid, PASS_SCORE)
        _status_is(monkeypatch, "interrupted")

        assert client.post(f"/api/v1/candidates/{cid}/resume").status_code == 202
        assert enqueued == [("process", None)]
