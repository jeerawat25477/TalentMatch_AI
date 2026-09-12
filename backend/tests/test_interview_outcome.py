"""บันทึกผลสัมภาษณ์จริง (routers/interview_outcome).

รัน: docker compose exec backend python -m pytest tests/test_interview_outcome.py -v

สิ่งที่เทสชุดนี้กัน:
1. **ห้ามแตะ hr_decisions เด็ดขาด** — ผลสัมภาษณ์กับคำตัดสินคัดกรองเป็นคนละเรื่อง
   ถ้าปนกัน route_candidates จะถูกปลุกให้ตัดสินใหม่โดยไม่มีใครสั่ง แล้วผู้สมัครที่
   สัมภาษณ์ไม่ผ่านจะถูกร่างอีเมลปฏิเสธส่งออกเองเงียบ ๆ
2. **ขั้นเลื่อนขึ้นได้อย่างเดียว ห้ามย้อน** — บันทึกผลย้อนหลังต้องไม่ดึงคนที่ยื่นข้อเสนอ
   ไปแล้วกลับมาที่ "สัมภาษณ์แล้ว" และต้องไม่ปลุกการ์ดที่ HR จงใจพักไว้ที่ "ไม่ไปต่อ"
3. **หนึ่งคนหนึ่งผล** — ยิงซ้ำต้องทับของเดิม ไม่ใช่งอกแถวใหม่
4. ทั้งสองเควรีที่คืน BoardItem ต้องมี interview_result ตรงกัน ไม่ใช่แค่ GET /board
"""
import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_conn
from app.main import app
from app.routers.interview_outcome import _next_stage_after_outcome

PASS_SCORE = 85  # > AUTO_ADVANCE_ABOVE จึงขึ้นกระดานเอง


# ---------- กฎการเลื่อนขั้น (ฟังก์ชันบริสุทธิ์ ไม่ต่อ DB) ----------


class TestNextStageAfterOutcome:
    @pytest.mark.parametrize("current", [None, "invited", "scheduled"])
    def test_ขั้นก่อนหน้าเลื่อนขึ้นเป็นสัมภาษณ์แล้ว(self, current):
        """HR ทำงานเดียวได้สองอย่าง ไม่ต้องกลับไปลากการ์ดซ้ำอีกรอบ."""
        assert _next_stage_after_outcome(current) == "interviewed"

    def test_อยู่ที่สัมภาษณ์แล้วไม่ต้องเขียนซ้ำ(self):
        """เขียนทับค่าเดิมจะทำให้ moved_at ขยับเปล่า ๆ ทั้งที่ไม่มีใครย้ายอะไร."""
        assert _next_stage_after_outcome("interviewed") is None

    def test_ยื่นข้อเสนอแล้วห้ามย้อนกลับ(self):
        assert _next_stage_after_outcome("offer") is None

    def test_ไม่ไปต่ออยู่นอกบันไดจึงไม่แตะ(self):
        """ลากกลับมาเท่ากับปลุกการ์ดที่ HR จงใจพักไว้."""
        assert _next_stage_after_outcome("declined") is None


# ---------- ฝั่ง endpoint (ใช้ DB จริงในคอนเทนเนอร์) ----------


@pytest.fixture
def anon() -> TestClient:
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: "admin-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def job_and_candidate():
    """งาน + ผู้สมัครคะแนนผ่านของตัวเอง แล้วลบทิ้ง — ไม่แตะข้อมูลจริง."""
    with get_conn() as conn:
        job = conn.execute(
            "INSERT INTO jobs (title, raw_text) VALUES (%s, %s) RETURNING id",
            ("เทสผลสัมภาษณ์ (ลบได้)", "ต้องมี Python"),
        ).fetchone()
        cand = conn.execute(
            "INSERT INTO candidates (job_id, full_name) VALUES (%s, %s) RETURNING id",
            (job["id"], "ผู้สมัครผลสัมภาษณ์"),
        ).fetchone()
        conn.execute(
            "INSERT INTO evaluations (job_id, candidate_id, fit_score) VALUES (%s, %s, %s)",
            (job["id"], cand["id"], PASS_SCORE),
        )
        conn.commit()
    yield str(job["id"]), str(cand["id"])
    with get_conn() as conn:
        conn.execute("DELETE FROM employees WHERE candidate_id = %s", (cand["id"],))
        conn.execute("DELETE FROM candidates WHERE id = %s", (cand["id"],))
        conn.execute("DELETE FROM jobs WHERE id = %s", (job["id"],))
        conn.commit()


def _set_stage(candidate_id: str, stage: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO hiring_stage (candidate_id, stage) VALUES (%s, %s)
               ON CONFLICT (candidate_id) DO UPDATE SET stage = EXCLUDED.stage""",
            (candidate_id, stage),
        )
        conn.commit()


def _stage_of(candidate_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT stage FROM hiring_stage WHERE candidate_id = %s", (candidate_id,)
        ).fetchone()
    return row["stage"] if row else None


def _outcome_rows(candidate_id: str) -> int:
    with get_conn() as conn:
        return conn.execute(
            "SELECT count(*) AS n FROM interview_outcome WHERE candidate_id = %s",
            (candidate_id,),
        ).fetchone()["n"]


def _decision_rows(candidate_id: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT decision, notes FROM hr_decisions WHERE candidate_id = %s",
            (candidate_id,),
        ).fetchall()


def _payload(**over) -> dict:
    body = {
        "result": "pass",
        "question_scores": [
            {"question": "เล่าประสบการณ์ Python", "score": 4, "note": "ตอบได้ดี"},
            {"question": "เคยใช้ Docker ไหม", "score": None, "note": None},
        ],
        "overall_note": "ผ่านสบาย",
        "interviewed_at": "2026-09-10",
    }
    body.update(over)
    return body


class TestUpsert:
    def test_บันทึกครั้งแรกได้(self, client, job_and_candidate):
        _, cid = job_and_candidate
        r = client.put(f"/api/v1/candidates/{cid}/interview-outcome", json=_payload())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["result"] == "pass"
        assert body["interviewed_at"] == "2026-09-10"
        assert len(body["question_scores"]) == 2
        assert body["question_scores"][0]["score"] == 4
        assert _outcome_rows(cid) == 1

    def test_ยิงซ้ำทับของเดิมไม่ใช่งอกแถวใหม่(self, client, job_and_candidate):
        """หนึ่งคนหนึ่งผล เหมือน hr_decisions/employees/hiring_stage — ถ้างอกแถวใหม่
        ได้ จะไม่มีใครรู้ว่าผลไหนคือผลจริง."""
        _, cid = job_and_candidate
        client.put(f"/api/v1/candidates/{cid}/interview-outcome", json=_payload())
        first = client.get(f"/api/v1/candidates/{cid}").json()["interview_outcome"]

        r = client.put(
            f"/api/v1/candidates/{cid}/interview-outcome",
            json=_payload(result="fail", overall_note="คิดใหม่แล้ว", question_scores=[]),
        )
        assert r.status_code == 200
        assert _outcome_rows(cid) == 1
        assert r.json()["result"] == "fail"
        assert r.json()["overall_note"] == "คิดใหม่แล้ว"
        assert r.json()["question_scores"] == []
        # created_at ต้องคงเดิม (เป็นการแก้ ไม่ใช่การสร้างใหม่) ส่วน updated_at ขยับ
        assert r.json()["created_at"] == first["created_at"]
        assert r.json()["updated_at"] >= first["updated_at"]

    def test_ผู้สมัครไม่มีจริงได้_404(self, client):
        r = client.put(
            "/api/v1/candidates/00000000-0000-0000-0000-000000000000/interview-outcome",
            json=_payload(),
        )
        assert r.status_code == 404

    @pytest.mark.parametrize("bad", ["passed", "hired", "", "PASS"])
    def test_ผลนอกสามค่าถูกปฏิเสธ(self, client, job_and_candidate, bad):
        _, cid = job_and_candidate
        r = client.put(
            f"/api/v1/candidates/{cid}/interview-outcome", json=_payload(result=bad)
        )
        assert r.status_code == 422
        assert _outcome_rows(cid) == 0

    @pytest.mark.parametrize("bad", [0, 6, -1, 100])
    def test_คะแนนรายข้อนอกช่วง_1ถึง5_ถูกปฏิเสธ(self, client, job_and_candidate, bad):
        """ช่วงนี้บังคับที่ Pydantic ที่เดียว เพราะ CHECK ตรวจค่าใน JSONB array ไม่ได้ —
        ถ้าด่านนี้หลุด จะไม่มีอะไรกันเลย."""
        _, cid = job_and_candidate
        r = client.put(
            f"/api/v1/candidates/{cid}/interview-outcome",
            json=_payload(question_scores=[{"question": "ถามอะไรสักอย่าง", "score": bad}]),
        )
        assert r.status_code == 422
        assert _outcome_rows(cid) == 0

    def test_ต้องล็อกอินก่อน(self, anon, job_and_candidate):
        _, cid = job_and_candidate
        r = anon.put(f"/api/v1/candidates/{cid}/interview-outcome", json=_payload())
        assert r.status_code == 401


class TestStageAdvance:
    def test_ยังไม่มีแถวขั้นเลยจะถูกสร้างเป็นสัมภาษณ์แล้ว(self, client, job_and_candidate):
        _, cid = job_and_candidate
        assert _stage_of(cid) is None
        client.put(f"/api/v1/candidates/{cid}/interview-outcome", json=_payload())
        assert _stage_of(cid) == "interviewed"

    @pytest.mark.parametrize("start", ["invited", "scheduled"])
    def test_ขั้นก่อนหน้าเลื่อนขึ้นเอง(self, client, job_and_candidate, start):
        _, cid = job_and_candidate
        _set_stage(cid, start)
        client.put(f"/api/v1/candidates/{cid}/interview-outcome", json=_payload())
        assert _stage_of(cid) == "interviewed"

    @pytest.mark.parametrize("start", ["offer", "declined"])
    def test_ขั้นที่ไปไกลกว่าหรืออยู่นอกบันไดต้องไม่ถูกย้อน(
        self, client, job_and_candidate, start
    ):
        _, cid = job_and_candidate
        _set_stage(cid, start)
        client.put(f"/api/v1/candidates/{cid}/interview-outcome", json=_payload())
        assert _stage_of(cid) == start


class TestDoesNotTouchScreeningDecision:
    def test_ไม่มีคำตัดสินอยู่ก่อนก็ต้องไม่สร้างขึ้นมา(self, client, job_and_candidate):
        """ถ้าเผลอ upsert hr_decisions ที่นี่ กราฟจะถูกปลุกให้ตัดสินใหม่โดยไม่มีใครสั่ง."""
        _, cid = job_and_candidate
        assert _decision_rows(cid) == []
        client.put(
            f"/api/v1/candidates/{cid}/interview-outcome", json=_payload(result="fail")
        )
        assert _decision_rows(cid) == []

    def test_คำตัดสินเดิมต้องไม่ถูกแก้แม้ผลสัมภาษณ์จะสวนทาง(self, client, job_and_candidate):
        """HR อนุมัติให้ไปสัมภาษณ์ แล้วสัมภาษณ์ไม่ผ่าน — สองอย่างนี้อยู่ด้วยกันได้
        และต้องอยู่ด้วยกันได้ เพราะตอบคนละคำถาม."""
        _, cid = job_and_candidate
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO hr_decisions (candidate_id, decision, notes)
                   VALUES (%s, 'approved', 'ให้ไปสัมภาษณ์')""",
                (cid,),
            )
            conn.commit()
        before = _decision_rows(cid)

        client.put(
            f"/api/v1/candidates/{cid}/interview-outcome", json=_payload(result="fail")
        )

        assert _decision_rows(cid) == before
        assert before[0]["decision"] == "approved"


class TestSurfacedInExistingResponses:
    def test_รายละเอียดผู้สมัครคืน_null_ตอนยังไม่เคยบันทึก(self, client, job_and_candidate):
        """กันบั๊ก to_jsonb ที่คืน object ที่มีแต่ค่า null แทน NULL บน LEFT JOIN ที่ไม่
        แมตช์ ซึ่งจะทำให้ผู้สมัครเกือบทุกคนในระบบเปิดหน้าไม่ได้."""
        _, cid = job_and_candidate
        r = client.get(f"/api/v1/candidates/{cid}")
        assert r.status_code == 200
        assert r.json()["interview_outcome"] is None

    def test_รายละเอียดผู้สมัครคืนผลครบหลังบันทึก(self, client, job_and_candidate):
        _, cid = job_and_candidate
        client.put(f"/api/v1/candidates/{cid}/interview-outcome", json=_payload())
        got = client.get(f"/api/v1/candidates/{cid}").json()["interview_outcome"]
        assert got["result"] == "pass"
        assert got["overall_note"] == "ผ่านสบาย"
        assert got["interviewed_at"] == "2026-09-10"
        assert got["question_scores"][0]["note"] == "ตอบได้ดี"

    def test_กระดานและการย้ายขั้นคืนผลตรงกัน(self, client, job_and_candidate):
        """ทั้งสองเส้นทางประกาศ response_model เดียวกันคือ BoardItem — ถ้าเติมฟิลด์
        แค่ใน GET /board อันที่ขาดก็เป็นกับดักรอผู้เรียกรายต่อไปที่เชื่อสัญญาแล้วเอา
        response ของ PATCH ไปวาดการ์ดตรง ๆ (หน้ากระดานตอนนี้ทิ้งแล้ว revalidate เอา)."""
        job_id, cid = job_and_candidate
        client.put(
            f"/api/v1/candidates/{cid}/interview-outcome", json=_payload(result="standby")
        )

        board = client.get(f"/api/v1/jobs/{job_id}/board").json()
        card = next(c for c in board if c["candidate_id"] == cid)
        assert card["interview_result"] == "standby"
        assert card["stage"] == "interviewed"  # เลื่อนขึ้นเองแล้ว

        moved = client.patch(f"/api/v1/candidates/{cid}/stage", json={"stage": "offer"})
        assert moved.status_code == 200
        assert moved.json()["interview_result"] == "standby"

    def test_ยังไม่เคยบันทึกการ์ดต้องคืน_null_ไม่ใช่พัง(self, client, job_and_candidate):
        job_id, cid = job_and_candidate
        board = client.get(f"/api/v1/jobs/{job_id}/board").json()
        card = next(c for c in board if c["candidate_id"] == cid)
        assert card["interview_result"] is None
