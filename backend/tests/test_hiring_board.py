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
from app.hiring_board import board_stage, has_screening_conflict, is_board_eligible
from app.main import app
from app.routers.hiring_board import _FUNNEL_LABELS, _funnel_flags

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


class TestBoardStage:
    def test_ไม่เข้าเกณฑ์และไม่มีแถวคือไม่อยู่บนกระดาน(self):
        assert board_stage(None, False, None, FAIL_SCORE) is None
        assert board_stage(None, False, "rejected", PASS_SCORE) is None

    def test_เข้าเกณฑ์แต่ยังไม่ย้ายคือ_invited(self):
        assert board_stage(None, False, None, PASS_SCORE) == "invited"
        assert board_stage(None, False, "approved", REVIEW_SCORE) == "invited"

    def test_มีแถวใช้ค่าในแถว_แม้ตกเกณฑ์ทีหลัง(self):
        assert board_stage("offer", False, "rejected", PASS_SCORE) == "offer"

    def test_มีระเบียนพนักงานคือ_hired_เสมอ(self):
        assert board_stage("interviewed", True, "approved", PASS_SCORE) == "hired"
        assert board_stage(None, True, None, None) == "hired"


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


class TestDetailSeesSameStage:
    def test_หน้ารายละเอียดเห็นขั้นเดียวกับกระดาน(self, client, job_and_candidate):
        """เดิมหน้ารายละเอียดไม่รู้ขั้นเลย — HR ต้องสลับสองหน้าแล้วต่อภาพเอง."""
        job_id, cid = job_and_candidate
        detail = client.get(f"/api/v1/candidates/{cid}").json()
        assert detail["board_stage"] == "invited" and detail["stage_moved_at"] is None

        client.patch(f"/api/v1/candidates/{cid}/stage", json={"stage": "offer"})
        detail = client.get(f"/api/v1/candidates/{cid}").json()
        board = client.get(f"/api/v1/jobs/{job_id}/board").json()
        assert detail["board_stage"] == board[0]["stage"] == "offer"
        assert detail["stage_moved_at"] is not None


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


# ---------- funnel รวมผู้สมัครทั้งตำแหน่ง ----------

# ค่าที่เป็นไปได้ของแต่ละแกน ใช้ไล่ทุกคู่ผสมเพื่อยืนยันว่ากรวยไม่มีวันกว้างขึ้นตอนปลาย
_STAGES = [None, "invited", "scheduled", "interviewed", "offer", "declined"]
_DECISIONS = [None, "approved", "rejected"]
_SCORES = [None, PASS_SCORE, REVIEW_SCORE, FAIL_SCORE]


class TestFunnelFlags:
    """กฎว่าใครถูกนับในขั้นไหน (ฟังก์ชันบริสุทธิ์ ไม่ต่อ DB)."""

    @pytest.mark.parametrize("has_outcome", [False, True])
    @pytest.mark.parametrize("has_employee", [False, True])
    @pytest.mark.parametrize("score", _SCORES)
    @pytest.mark.parametrize("decision", _DECISIONS)
    @pytest.mark.parametrize("stage", _STAGES)
    def test_ขั้นหลังต้องซ้อนอยู่ในขั้นก่อนเสมอ(
        self, stage, decision, score, has_employee, has_outcome
    ):
        """เงื่อนไขเดียวที่ทำให้กรวยอ่านรู้เรื่อง: จำนวนลดหลั่นลงเท่านั้น ห้ามเพิ่ม."""
        flags = _funnel_flags(stage, has_employee, decision, score, has_outcome)
        assert len(flags) == len(_FUNNEL_LABELS)
        assert flags[0] is True
        for earlier, later in zip(flags, flags[1:]):
            assert earlier or not later, flags

    def test_คนที่รับเข้าแล้วถูกนับครบทุกขั้น(self):
        """แม้ไม่เคยมีแถว hiring_stage (ปุ่มรับเข้าไม่สร้างแถวขั้น) และคะแนนตกเกณฑ์ —
        ถ้าไล่ and จากบนลงล่าง คนคนนี้จะหายไปจากทุกขั้นเงียบ ๆ."""
        assert _funnel_flags(None, True, "rejected", FAIL_SCORE, False) == [True] * 5

    def test_บันทึกผลสัมภาษณ์แล้วนับว่าสัมภาษณ์แล้ว(self):
        """HR อาจกรอกผลโดยไม่ได้ลากการ์ดไปขั้น 'สัมภาษณ์แล้ว'."""
        flags = _funnel_flags("scheduled", False, None, PASS_SCORE, True)
        assert flags == [True, True, True, True, False]

    def test_นัดแล้วยังไม่นับว่าสัมภาษณ์แล้ว(self):
        assert _funnel_flags("scheduled", False, None, PASS_SCORE, False) == [
            True, True, True, False, False
        ]

    def test_ยื่นข้อเสนอแล้วนับว่าผ่านสัมภาษณ์มาแล้ว(self):
        assert _funnel_flags("offer", False, None, PASS_SCORE, False) == [
            True, True, True, True, False
        ]

    def test_ผู้สมัครถอนตัวไม่นับว่าถูกนัด_แต่ยังผ่านคัดกรอง(self):
        """'declined' คือถอนตัว — แต่มีแถวแล้วแปลว่าผ่านคัดกรองมาแล้ว (กฎเดียวกับกระดาน)."""
        assert _funnel_flags("declined", False, None, FAIL_SCORE, False) == [
            True, True, False, False, False
        ]

    def test_คะแนนไม่ถึงและไม่มีอะไรเลยนับแค่ขั้นสมัคร(self):
        assert _funnel_flags(None, False, None, FAIL_SCORE, False) == [
            True, False, False, False, False
        ]

    def test_ขั้นคัดกรองใช้เกณฑ์เดียวกับกระดานไม่ใช่เลข_70_ที่พิมพ์ซ้ำ(self, monkeypatch):
        """เลื่อนเส้นแบ่งใน bands แล้วตัวเลข funnel ต้องเลื่อนตาม ไม่งั้นคือมีสองมาตรฐาน."""
        assert _funnel_flags(None, False, None, REVIEW_SCORE, False)[1] is False
        monkeypatch.setattr(bands, "AUTO_ADVANCE_ABOVE", REVIEW_SCORE - 1)
        assert _funnel_flags(None, False, None, REVIEW_SCORE, False)[1] is True


class TestGetFunnel:
    def test_ต้องล็อกอินก่อนดู_funnel(self, anon, job_and_candidate):
        job_id, _ = job_and_candidate
        assert anon.get(f"/api/v1/jobs/{job_id}/funnel").status_code == 401

    def test_ตำแหน่งที่ยังไม่มีผู้สมัครได้ศูนย์ทุกขั้นไม่ใช่_error(self, client):
        with get_conn() as conn:
            job = conn.execute(
                "INSERT INTO jobs (title, raw_text) VALUES (%s, %s) RETURNING id",
                ("เทส funnel ว่าง (ลบได้)", "ต้องมี Python"),
            ).fetchone()
            conn.commit()
        try:
            r = client.get(f"/api/v1/jobs/{job['id']}/funnel")
            assert r.status_code == 200
            assert [s["count"] for s in r.json()] == [0] * len(_FUNNEL_LABELS)
            assert [s["label"] for s in r.json()] == _FUNNEL_LABELS
        finally:
            with get_conn() as conn:
                conn.execute("DELETE FROM jobs WHERE id = %s", (job["id"],))
                conn.commit()

    @pytest.fixture
    def job_every_stage(self):
        """ตำแหน่งที่มีคนอยู่ครบทุกขั้น คนละหนึ่งคน + คนคะแนนตกที่ไม่ผ่านคัดกรอง."""
        people = [
            # (ชื่อ, คะแนน, ขั้นในตาราง, มีผลสัมภาษณ์, รับเข้าแล้ว)
            ("ตกคัดกรอง", FAIL_SCORE, None, False, False),
            ("ผ่านคัดกรองเฉย ๆ", PASS_SCORE, None, False, False),
            ("นัดแล้ว", PASS_SCORE, "scheduled", False, False),
            ("สัมภาษณ์แล้ว", PASS_SCORE, "interviewed", True, False),
            ("รับเข้าแล้ว", PASS_SCORE, "offer", True, True),
        ]
        with get_conn() as conn:
            job = conn.execute(
                "INSERT INTO jobs (title, raw_text) VALUES (%s, %s) RETURNING id",
                ("เทส funnel ครบขั้น (ลบได้)", "ต้องมี Python"),
            ).fetchone()
            for name, score, stage, outcome, hired in people:
                cand = conn.execute(
                    "INSERT INTO candidates (job_id, full_name) VALUES (%s, %s) RETURNING id",
                    (job["id"], name),
                ).fetchone()
                conn.execute(
                    """INSERT INTO evaluations (job_id, candidate_id, fit_score)
                       VALUES (%s, %s, %s)""",
                    (job["id"], cand["id"], score),
                )
                if stage:
                    conn.execute(
                        "INSERT INTO hiring_stage (candidate_id, stage) VALUES (%s, %s)",
                        (cand["id"], stage),
                    )
                if outcome:
                    conn.execute(
                        "INSERT INTO interview_outcome (candidate_id, result) VALUES (%s, 'pass')",
                        (cand["id"],),
                    )
                if hired:
                    conn.execute(
                        """INSERT INTO employees (candidate_id, job_id, full_name, position)
                           VALUES (%s, %s, %s, %s)""",
                        (cand["id"], job["id"], name, "Backend Developer"),
                    )
            conn.commit()
        yield str(job["id"])
        with get_conn() as conn:
            conn.execute("DELETE FROM employees WHERE job_id = %s", (job["id"],))
            conn.execute("DELETE FROM candidates WHERE job_id = %s", (job["id"],))
            conn.execute("DELETE FROM jobs WHERE id = %s", (job["id"],))
            conn.commit()

    def test_นับครบทุกขั้นและลดหลั่นลง(self, client, job_every_stage):
        counts = [
            s["count"]
            for s in client.get(f"/api/v1/jobs/{job_every_stage}/funnel").json()
        ]
        # สมัคร 5 · ผ่านคัดกรอง 4 (ตัดคนคะแนนตก) · ถูกนัด 3 · สัมภาษณ์ 2 · รับเข้า 1
        assert counts == [5, 4, 3, 2, 1]

    def test_ขั้นคัดกรองตรงกับจำนวนการ์ดบนกระดานจริง(self, client, job_every_stage):
        """สองหน้าต้องไม่บอกคนละเลข — เหตุผลที่ funnel เรียก is_board_eligible ตัวเดียวกัน."""
        funnel = client.get(f"/api/v1/jobs/{job_every_stage}/funnel").json()
        board = client.get(f"/api/v1/jobs/{job_every_stage}/board").json()
        assert funnel[1]["count"] == len(board)

    def test_funnel_ต้องไม่สร้างแถว_hiring_stage(self, client, job_every_stage):
        """อ่านอย่างเดียวเหมือน get_board — write-on-read ทำให้ moved_at ไร้ความหมาย."""
        sql = """SELECT count(*) AS n FROM hiring_stage hs
                   JOIN candidates c ON c.id = hs.candidate_id WHERE c.job_id = %s"""
        with get_conn() as conn:
            before = conn.execute(sql, (job_every_stage,)).fetchone()["n"]
        client.get(f"/api/v1/jobs/{job_every_stage}/funnel")
        with get_conn() as conn:
            after = conn.execute(sql, (job_every_stage,)).fetchone()["n"]
        assert before == after == 3


class TestTimelineFields:
    """เวลาที่หน้ารายละเอียดใช้วาดไทม์ไลน์ — ต้องมาครบและต้องเป็น null ได้โดยไม่พัง."""

    def test_ผู้สมัครที่ยังไม่มีอะไรเลยได้_null_ไม่ใช่_500(self, client, job_and_candidate):
        """คนที่ถูกปฏิเสธไปแล้วไม่มีทั้งขั้นบนกระดาน ผลสัมภาษณ์ และวันรับเข้า
        ซึ่งเป็นคนส่วนใหญ่ในระบบ — จุดที่ไม่มีข้อมูลต้องหายไปจากไทม์ไลน์ ไม่ใช่ error."""
        _, cid = job_and_candidate
        r = client.get(f"/api/v1/candidates/{cid}")
        assert r.status_code == 200
        body = r.json()
        assert body["evaluated_at"] is not None      # มีผลวิเคราะห์แล้ว (fixture ใส่ให้)
        assert body["hired_at"] is None
        assert body["stage_moved_at"] is None
        assert body["interview_outcome"] is None

    def test_รับเข้าแล้วได้เวลารับเข้ามาด้วย(self, client, job_and_candidate):
        job_id, cid = job_and_candidate
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO employees (candidate_id, job_id, full_name, position)
                   VALUES (%s, %s, %s, %s)""",
                (cid, job_id, "ผู้สมัครกระดาน", "Backend Developer"),
            )
            conn.commit()
        body = client.get(f"/api/v1/candidates/{cid}").json()
        assert body["employee_id"] is not None
        assert body["hired_at"] is not None
