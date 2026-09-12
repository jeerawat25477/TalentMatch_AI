"""กระดานติดตามผู้สมัคร (app.hiring_board + routers/hiring_board).

รัน: docker compose exec backend python -m pytest tests/test_hiring_board.py -v

สิ่งที่เทสชุดนี้กัน:
1. **คำตัดสินของ HR ต้องชนะคะแนนเสมอ** — หัวใจเดียวกับ graph.py::route_candidates
   ถ้าพลาดข้อนี้ ปุ่มที่ HR กดก็ไม่มีความหมาย เพราะคะแนนของ AI ยังชนะอยู่ดี
2. **เส้นแบ่งคะแนนต้องมาจาก bands.py ที่เดียว** ไม่ใช่เลข 70 ที่พิมพ์ซ้ำในไฟล์ใหม่
3. **"รับเข้าแล้ว" ไม่ใช่ค่าใน stage** — ต้องมาจากการมีระเบียนพนักงานเท่านั้น
4. GET ต้องไม่เขียนอะไร (write-on-read ทำให้ moved_at ไร้ความหมาย)
"""
import pytest
from fastapi.testclient import TestClient

from app.agents import bands
from app.auth import get_current_user
from app.database import get_conn
from app.hiring_board import has_screening_conflict, is_board_eligible
from app.main import app

PASS_SCORE = 85     # > AUTO_ADVANCE_ABOVE
REVIEW_SCORE = 60   # 50-70 — กราฟหยุดรอ HR
FAIL_SCORE = 20     # < REVIEW_FROM


# ---------- กฎว่าใครขึ้นกระดาน (ฟังก์ชันบริสุทธิ์ ไม่ต่อ DB) ----------


class TestIsBoardEligible:
    def test_คะแนนผ่านอัตโนมัติขึ้นกระดาน(self):
        assert is_board_eligible(False, None, PASS_SCORE) is True

    def test_คะแนนช่วงรอ_hr_ยังไม่ขึ้นกระดาน(self):
        """ช่วง 50-70 กราฟหยุดรอคำตัดสินอยู่ ยังไม่มีใครตัดสิน — ซ้ำกับแท็บ Needs Review."""
        assert is_board_eligible(False, None, REVIEW_SCORE) is False

    def test_คะแนนไม่ผ่านไม่ขึ้นกระดาน(self):
        assert is_board_eligible(False, None, FAIL_SCORE) is False

    def test_ยังไม่มีคะแนนไม่ขึ้นกระดาน(self):
        """กราฟยังวิเคราะห์ไม่เสร็จ — ยังไม่มีอะไรให้ติดตาม."""
        assert is_board_eligible(False, None, None) is False

    def test_hr_อนุมัติชนะคะแนนต่ำ(self):
        """หัวใจของ router: มนุษย์มีอำนาจสูงสุด ไม่ใช่แค่ปุ่มที่กดแล้วคะแนน AI ยังชนะ."""
        assert is_board_eligible(False, "approved", FAIL_SCORE) is True
        assert is_board_eligible(False, "approved", None) is True

    def test_hr_ปฏิเสธชนะคะแนนสูง(self):
        assert is_board_eligible(False, "rejected", PASS_SCORE) is False

    @pytest.mark.parametrize("decision", [None, "approved", "rejected", "pending"])
    @pytest.mark.parametrize("score", [PASS_SCORE, REVIEW_SCORE, FAIL_SCORE, None])
    def test_มีการ์ดแล้วห้ามหายเงียบไม่ว่าอะไรจะเปลี่ยน(self, decision, score):
        """HR นัดสัมภาษณ์คนนั้นไปแล้ว การ์ดที่หายเองกลางทาง = งานที่ทำไปแล้วหายไปด้วย
        โดยไม่มีใครรู้ · เคสที่ขัดกันขึ้นป้ายเตือนแทน (ดู has_screening_conflict)."""
        assert is_board_eligible(True, decision, score) is True

    def test_ต้องเรียก_bands_จริงไม่ใช่ฮาร์ดโค้ดเลข_70(self, monkeypatch):
        """ถ้าใครเผลอเขียน `fit_score > 70` ในไฟล์ใหม่ เทสนี้จะจับได้ทันที.

        เลื่อนเส้นแบ่งใน bands แล้วผลของกระดานต้องเลื่อนตาม — บทเรียนเดิมคือเลข 50/70
        เคยกระจายอยู่ 6 ที่จนป้ายสีในเว็บกับเส้นทางที่กราฟเดินจริงหลุดกันแบบเงียบ ๆ
        """
        assert is_board_eligible(False, None, REVIEW_SCORE) is False
        monkeypatch.setattr(bands, "AUTO_ADVANCE_ABOVE", REVIEW_SCORE - 1)
        assert is_board_eligible(False, None, REVIEW_SCORE) is True


class TestHasScreeningConflict:
    def test_ไม่มีการ์ดก็ไม่มีความขัดแย้ง(self):
        for score in (PASS_SCORE, REVIEW_SCORE, FAIL_SCORE, None):
            assert has_screening_conflict(False, None, score) is False
            assert has_screening_conflict(False, "rejected", score) is False

    def test_มีการ์ดและยังเข้าเกณฑ์อยู่ไม่ถือว่าขัดแย้ง(self):
        assert has_screening_conflict(True, None, PASS_SCORE) is False
        assert has_screening_conflict(True, "approved", FAIL_SCORE) is False

    def test_hr_กลับคำหลังการ์ดขึ้นกระดานแล้วคือขัดแย้ง(self):
        assert has_screening_conflict(True, "rejected", PASS_SCORE) is True

    def test_คะแนนตกเกณฑ์หลังมีการ์ดแล้วก็ถือว่าขัดแย้ง(self):
        """เช่นถูกคำนวณคะแนนใหม่ด้วย recompute_scores แล้วตกลงมา."""
        assert has_screening_conflict(True, None, FAIL_SCORE) is True


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
    """งาน + ผู้สมัครคะแนนผ่านหนึ่งคนของตัวเอง แล้วลบทิ้ง — ไม่แตะข้อมูลจริง."""
    with get_conn() as conn:
        job = conn.execute(
            "INSERT INTO jobs (title, raw_text) VALUES (%s, %s) RETURNING id",
            ("เทสกระดาน (ลบได้)", "ต้องมี Python"),
        ).fetchone()
        cand = conn.execute(
            "INSERT INTO candidates (job_id, full_name) VALUES (%s, %s) RETURNING id",
            (job["id"], "ผู้สมัครกระดาน"),
        ).fetchone()
        conn.execute(
            """INSERT INTO evaluations (job_id, candidate_id, fit_score)
               VALUES (%s, %s, %s)""",
            (job["id"], cand["id"], PASS_SCORE),
        )
        conn.commit()
    yield str(job["id"]), str(cand["id"])
    with get_conn() as conn:
        conn.execute("DELETE FROM employees WHERE candidate_id = %s", (cand["id"],))
        conn.execute("DELETE FROM candidates WHERE id = %s", (cand["id"],))
        conn.execute("DELETE FROM jobs WHERE id = %s", (job["id"],))
        conn.commit()


def _stage_rows(candidate_id: str) -> int:
    with get_conn() as conn:
        return conn.execute(
            "SELECT count(*) AS n FROM hiring_stage WHERE candidate_id = %s",
            (candidate_id,),
        ).fetchone()["n"]


class TestAuthGate:
    def test_ต้องล็อกอินก่อนดูกระดาน(self, anon, job_and_candidate):
        job_id, _ = job_and_candidate
        assert anon.get(f"/api/v1/jobs/{job_id}/board").status_code == 401

    def test_ต้องล็อกอินก่อนย้ายขั้น(self, anon, job_and_candidate):
        _, cid = job_and_candidate
        r = anon.patch(f"/api/v1/candidates/{cid}/stage", json={"stage": "scheduled"})
        assert r.status_code == 401


class TestGetBoard:
    def test_คนคะแนนผ่านขึ้นกระดานเป็น_invited_โดยไม่ต้องมีแถว(self, client, job_and_candidate):
        job_id, cid = job_and_candidate
        body = client.get(f"/api/v1/jobs/{job_id}/board").json()
        assert [c["candidate_id"] for c in body] == [cid]
        assert body[0]["stage"] == "invited"
        assert body[0]["moved_at"] is None       # ยังไม่เคยย้ายจริง
        assert body[0]["employee_id"] is None
        assert body[0]["screening_conflict"] is False

    def test_get_ต้องไม่สร้างแถวในตาราง(self, client, job_and_candidate):
        """write-on-read ทำให้ moved_at กลายเป็น "เวลาที่ HR เปิดหน้า" ซึ่งไร้ความหมาย."""
        job_id, cid = job_and_candidate
        before = _stage_rows(cid)
        for _ in range(3):
            client.get(f"/api/v1/jobs/{job_id}/board")
        assert _stage_rows(cid) == before == 0


class TestPatchStage:
    def test_ย้ายขั้นได้และสร้างแถวให้เอง(self, client, job_and_candidate):
        _, cid = job_and_candidate
        r = client.patch(
            f"/api/v1/candidates/{cid}/stage",
            json={"stage": "scheduled", "note": "นัดวันจันทร์ 10 โมง"},
        )
        assert r.status_code == 200
        assert r.json()["stage"] == "scheduled"
        assert r.json()["moved_at"] is not None
        assert _stage_rows(cid) == 1

    def test_ย้ายซ้ำไม่สร้างแถวใหม่(self, client, job_and_candidate):
        _, cid = job_and_candidate
        client.patch(f"/api/v1/candidates/{cid}/stage", json={"stage": "scheduled"})
        client.patch(f"/api/v1/candidates/{cid}/stage", json={"stage": "interviewed"})
        assert _stage_rows(cid) == 1

    def test_ย้ายเป็น_hired_ต้องได้_400_ไม่ใช่_422(self, client, job_and_candidate):
        """ต้องเป็น 400 พร้อมข้อความที่บอกทางออก ไม่ใช่ error ดิบของ pydantic
        ที่ไม่ได้บอก HR ว่าให้ไปใช้ปุ่มรับเข้าเป็นพนักงานแทน."""
        _, cid = job_and_candidate
        r = client.patch(f"/api/v1/candidates/{cid}/stage", json={"stage": "hired"})
        assert r.status_code == 400
        assert "hire" in r.json()["detail"]
        assert _stage_rows(cid) == 0    # ต้องไม่เขียนอะไรทิ้งไว้

    def test_ค่านอกรายการต้อง_422(self, client, job_and_candidate):
        _, cid = job_and_candidate
        r = client.patch(f"/api/v1/candidates/{cid}/stage", json={"stage": "ไปดวงจันทร์"})
        assert r.status_code == 422

    def test_ไม่พบผู้สมัครต้อง_404(self, client):
        missing = "11111111-1111-1111-1111-111111111111"
        r = client.patch(f"/api/v1/candidates/{missing}/stage", json={"stage": "offer"})
        assert r.status_code == 404


class TestHiredCandidate:
    @pytest.fixture
    def hired(self, job_and_candidate):
        job_id, cid = job_and_candidate
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO employees (candidate_id, job_id, full_name, position)
                   VALUES (%s, %s, %s, %s)""",
                (cid, job_id, "ผู้สมัครกระดาน", "Backend Developer"),
            )
            conn.commit()
        return job_id, cid

    def test_คนที่จ้างแล้วขึ้นกระดานเป็น_hired_แบบอนุมาน(self, client, hired):
        """stage='hired' ไม่เคยถูกเก็บในคอลัมน์ — มาจากการมีระเบียนพนักงานเท่านั้น."""
        job_id, cid = hired
        item = next(
            c for c in client.get(f"/api/v1/jobs/{job_id}/board").json()
            if c["candidate_id"] == cid
        )
        assert item["stage"] == "hired"
        assert item["employee_id"] is not None
        assert _stage_rows(cid) == 0   # ไม่มีแถว แต่ยังคืน hired ได้

    def test_ย้ายขั้นคนที่จ้างแล้วต้องได้_409(self, client, hired):
        _, cid = hired
        r = client.patch(f"/api/v1/candidates/{cid}/stage", json={"stage": "scheduled"})
        assert r.status_code == 409
        assert "พนักงาน" in r.json()["detail"]


class TestScreeningConflictEndToEnd:
    def test_hr_กลับคำหลังการ์ดขึ้นแล้วต้องขึ้นป้ายเตือนแต่ไม่หาย(self, client, job_and_candidate):
        job_id, cid = job_and_candidate
        client.patch(f"/api/v1/candidates/{cid}/stage", json={"stage": "interviewed"})
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO hr_decisions (candidate_id, decision)
                   VALUES (%s, 'rejected')""",
                (cid,),
            )
            conn.commit()

        item = next(
            c for c in client.get(f"/api/v1/jobs/{job_id}/board").json()
            if c["candidate_id"] == cid
        )
        assert item["screening_conflict"] is True
        assert item["stage"] == "interviewed"   # การ์ดยังอยู่ ไม่หายไปเอง


class TestDeletionStillWorks:
    def test_ลบผู้สมัครที่มีแถว_stage_ได้และแถวหายตาม(self, client, job_and_candidate):
        """การ์ดกันลบเดิมไม่ต้องเพิ่มเงื่อนไข — hiring_stage cascade หายตามอยู่แล้ว."""
        _, cid = job_and_candidate
        client.patch(f"/api/v1/candidates/{cid}/stage", json={"stage": "offer"})
        assert _stage_rows(cid) == 1

        assert client.delete(f"/api/v1/candidates/{cid}").status_code == 200
        assert _stage_rows(cid) == 0
