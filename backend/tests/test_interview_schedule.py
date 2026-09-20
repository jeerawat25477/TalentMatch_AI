"""วันเวลานัดสัมภาษณ์บน hiring_stage (routers/hiring_board.update_stage).

รัน: docker compose exec backend python -m pytest tests/test_interview_schedule.py -v

สิ่งที่เทสชุดนี้กัน:
1. **partial update** — ลากการ์ดย้ายขั้นต้องไม่ลบวันนัดทิ้ง · ส่ง null ตรง ๆ ต้องล้างได้
   (ถ้าใช้ COALESCE แทน HR จะล้างวันนัดที่กรอกผิดไม่ได้เลย)
2. **บันทึกวันนัดโดยไม่ย้ายขั้นต้องไม่ขยับ moved_at** — คอลัมน์นั้นแปลว่า "ย้ายขั้นล่าสุด"
3. **เวลาต้องมีโซนเสมอ** — เวลาไม่มีโซนถูก Postgres ตีเป็น UTC แล้วนัดบ่ายสองของ HR
   ในไทยจะกลายเป็นสามทุ่มในปฏิทินแบบเงียบ ๆ
4. หน้ากระดาน, response ของ PATCH และหน้ารายละเอียดเห็นค่าเดียวกัน
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_conn
from app.main import app
from app.routers.hiring_board import _is_overdue, _schedule_patch
from app.schemas import StageUpdate

PASS_SCORE = 85  # ขึ้นกระดานเอง
AT = "2026-09-21T14:00:00+07:00"  # บ่ายสองโมงเวลาไทย
AT_UTC = datetime(2026, 9, 21, 7, 0, tzinfo=timezone.utc)


# ---------- แยกฟิลด์ที่ถูกส่งมา (ฟังก์ชันบริสุทธิ์ ไม่ต่อ DB) ----------


class TestSchedulePatch:
    def test_ไม่ส่งฟิลด์มาเลยคือคงค่าเดิม(self):
        p = _schedule_patch(StageUpdate(stage="offer"))
        assert p["set_scheduled_at"] is False and p["set_location"] is False

    def test_ส่ง_null_มาตรง_ๆ_คือล้างค่า(self):
        p = _schedule_patch(StageUpdate(stage="scheduled", scheduled_at=None, location=None))
        assert p["set_scheduled_at"] is True and p["scheduled_at"] is None
        assert p["set_location"] is True and p["location"] is None

    def test_ส่งค่ามาคือเขียนค่าใหม่(self):
        p = _schedule_patch(StageUpdate(stage="scheduled", scheduled_at=AT, location=" ห้อง 3 "))
        assert p["set_scheduled_at"] is True and p["scheduled_at"] == AT_UTC
        assert p["location"] == "ห้อง 3"

    def test_สถานที่ที่เป็นช่องว่างล้วนนับเป็นการล้าง(self):
        p = _schedule_patch(StageUpdate(stage="scheduled", location="   "))
        assert p["set_location"] is True and p["location"] is None


# ---------- ฝั่ง endpoint (ใช้ DB จริงในคอนเทนเนอร์) ----------


@pytest.fixture
def anon() -> TestClient:
    """ไม่ล็อกอิน — ใช้ยืนยันว่า endpoint ใหม่ถูกกันด้วย JWT เหมือนทุกเส้นทางอื่น."""
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
            ("เทสวันนัด (ลบได้)", "ต้องมี Python"),
        ).fetchone()
        cand = conn.execute(
            "INSERT INTO candidates (job_id, full_name, email) VALUES (%s, %s, %s) RETURNING id",
            (job["id"], "ผู้สมัครวันนัด", "candidate@example.com"),
        ).fetchone()
        conn.execute(
            "INSERT INTO evaluations (job_id, candidate_id, fit_score) VALUES (%s, %s, %s)",
            (job["id"], cand["id"], PASS_SCORE),
        )
        conn.commit()
    yield str(job["id"]), str(cand["id"])
    with get_conn() as conn:
        conn.execute("DELETE FROM candidates WHERE id = %s", (cand["id"],))
        conn.execute("DELETE FROM jobs WHERE id = %s", (job["id"],))
        conn.commit()


def _patch(client, cid, **body):
    return client.patch(f"/api/v1/candidates/{cid}/stage", json=body)


def _row(cid):
    with get_conn() as conn:
        return conn.execute(
            "SELECT stage, moved_at, scheduled_at, location FROM hiring_stage WHERE candidate_id = %s",
            (cid,),
        ).fetchone()


class TestPartialUpdate:
    def test_ตั้งวันนัดและสถานที่ได้(self, client, job_and_candidate):
        _, cid = job_and_candidate
        r = _patch(client, cid, stage="scheduled", scheduled_at=AT, location="ออนไลน์ Google Meet")
        assert r.status_code == 200, r.text
        assert datetime.fromisoformat(r.json()["scheduled_at"]) == AT_UTC
        assert r.json()["location"] == "ออนไลน์ Google Meet"
        assert _row(cid)["scheduled_at"] == AT_UTC

    def test_ย้ายขั้นโดยไม่ส่งวันนัดต้องไม่ลบวันนัดเดิม(self, client, job_and_candidate):
        """ลากการ์ดจาก "นัดสัมภาษณ์" ไป "สัมภาษณ์แล้ว" ส่งแค่ stage — ถ้าเขียน NULL ทับ
        วันนัดจะหายทุกครั้งที่ขยับการ์ด."""
        _, cid = job_and_candidate
        _patch(client, cid, stage="scheduled", scheduled_at=AT, location="ห้องประชุม 2")
        r = _patch(client, cid, stage="interviewed")
        assert r.status_code == 200
        row = _row(cid)
        assert row["stage"] == "interviewed"
        assert row["scheduled_at"] == AT_UTC
        assert row["location"] == "ห้องประชุม 2"

    def test_ส่ง_null_ล้างวันนัดได้โดยไม่แตะสถานที่(self, client, job_and_candidate):
        _, cid = job_and_candidate
        _patch(client, cid, stage="scheduled", scheduled_at=AT, location="ห้องประชุม 2")
        _patch(client, cid, stage="scheduled", scheduled_at=None)
        row = _row(cid)
        assert row["scheduled_at"] is None
        assert row["location"] == "ห้องประชุม 2"

    def test_บันทึกวันนัดโดยไม่ย้ายขั้นต้องไม่ขยับ_moved_at(self, client, job_and_candidate):
        _, cid = job_and_candidate
        _patch(client, cid, stage="scheduled")
        before = _row(cid)["moved_at"]
        _patch(client, cid, stage="scheduled", scheduled_at=AT, location="ห้อง 1")
        assert _row(cid)["moved_at"] == before

    def test_ย้ายขั้นจริงยังขยับ_moved_at_ตามเดิม(self, client, job_and_candidate):
        _, cid = job_and_candidate
        _patch(client, cid, stage="scheduled")
        before = _row(cid)["moved_at"]
        _patch(client, cid, stage="offer")
        assert _row(cid)["moved_at"] > before

    def test_ตั้งวันนัดพร้อมสร้างแถวครั้งแรกได้(self, client, job_and_candidate):
        _, cid = job_and_candidate
        assert _row(cid) is None
        _patch(client, cid, stage="scheduled", scheduled_at=AT)
        assert _row(cid)["scheduled_at"] == AT_UTC


class TestValidation:
    def test_เวลาไม่มีโซนถูกปฏิเสธ(self, client, job_and_candidate):
        _, cid = job_and_candidate
        r = _patch(client, cid, stage="scheduled", scheduled_at="2026-09-21T14:00:00")
        assert r.status_code == 422
        assert _row(cid) is None

    def test_สถานที่ยาวเกินถูกปฏิเสธ(self, client, job_and_candidate):
        _, cid = job_and_candidate
        r = _patch(client, cid, stage="scheduled", location="ก" * 501)
        assert r.status_code == 422

    def test_ต้องล็อกอินก่อน(self, job_and_candidate):
        _, cid = job_and_candidate
        r = TestClient(app).patch(
            f"/api/v1/candidates/{cid}/stage", json={"stage": "scheduled", "scheduled_at": AT}
        )
        assert r.status_code == 401


class TestSurfacedEverywhere:
    def test_กระดานและหน้ารายละเอียดเห็นค่าเดียวกับที่บันทึก(self, client, job_and_candidate):
        job_id, cid = job_and_candidate
        _patch(client, cid, stage="scheduled", scheduled_at=AT, location="ออนไลน์")

        card = next(c for c in client.get(f"/api/v1/jobs/{job_id}/board").json()
                    if c["candidate_id"] == cid)
        detail = client.get(f"/api/v1/candidates/{cid}").json()
        for body in (card, detail):
            assert datetime.fromisoformat(body["scheduled_at"]) == AT_UTC
            assert body["location"] == "ออนไลน์"

    def test_ยังไม่ตั้งวันนัดคืน_null(self, client, job_and_candidate):
        job_id, cid = job_and_candidate
        card = client.get(f"/api/v1/jobs/{job_id}/board").json()[0]
        detail = client.get(f"/api/v1/candidates/{cid}").json()
        assert card["scheduled_at"] is None and card["location"] is None
        assert detail["scheduled_at"] is None and detail["location"] is None


# ---------- ตารางนัดสัมภาษณ์รวมทุกตำแหน่ง (GET /api/v1/interviews) ----------


class TestIsOverdue:
    """นัดที่เลยเวลาแล้วแต่ยังไม่บันทึกผล (ฟังก์ชันบริสุทธิ์ ไม่ต่อ DB)."""

    NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)

    def test_เลยเวลาแล้วยังไม่บันทึกผลคือค้าง(self):
        assert _is_overdue(self.NOW - timedelta(hours=2), False, self.NOW) is True

    def test_เลยเวลาแล้วแต่บันทึกผลแล้วไม่ค้าง(self):
        assert _is_overdue(self.NOW - timedelta(hours=2), True, self.NOW) is False

    def test_ยังไม่ถึงเวลานัดไม่ค้าง(self):
        assert _is_overdue(self.NOW + timedelta(hours=2), False, self.NOW) is False

    def test_ตรงเวลานัดพอดียังไม่นับว่าเลย(self):
        """สัมภาษณ์เพิ่งเริ่ม ขึ้นป้ายค้างทันทีตอนถึงเวลาคือรบกวนเปล่า ๆ."""
        assert _is_overdue(self.NOW, False, self.NOW) is False


class TestListInterviews:
    @pytest.fixture
    def scheduled_job(self):
        """ตำแหน่งที่มีนัดหลายแบบ — ไว้เช็คลำดับ ช่วงเวลา และกลุ่มที่ต้องถูกตัดออก."""
        base = datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)
        people = [
            # (ชื่อ, ขั้น, นัดเมื่อ, รับเข้าแล้ว)
            ("นัดวันที่สาม", "scheduled", base + timedelta(days=2), False),
            ("นัดวันแรก", "scheduled", base, False),
            ("ยุติแล้ว", "declined", base + timedelta(days=1), False),
            ("จ้างแล้ว", "offer", base + timedelta(days=1), True),
            ("ไม่มีวันนัด", "invited", None, False),
        ]
        with get_conn() as conn:
            job = conn.execute(
                "INSERT INTO jobs (title, raw_text) VALUES (%s, %s) RETURNING id",
                ("เทสตารางสัมภาษณ์ (ลบได้)", "ต้องมี Python"),
            ).fetchone()
            for name, stage, when, hired in people:
                cand = conn.execute(
                    "INSERT INTO candidates (job_id, full_name) VALUES (%s, %s) RETURNING id",
                    (job["id"], name),
                ).fetchone()
                conn.execute(
                    """INSERT INTO hiring_stage (candidate_id, stage, scheduled_at)
                       VALUES (%s, %s, %s)""",
                    (cand["id"], stage, when),
                )
                if hired:
                    conn.execute(
                        """INSERT INTO employees (candidate_id, job_id, full_name, position)
                           VALUES (%s, %s, %s, %s)""",
                        (cand["id"], job["id"], name, "Backend Developer"),
                    )
            conn.commit()
        yield str(job["id"]), base
        with get_conn() as conn:
            conn.execute("DELETE FROM employees WHERE job_id = %s", (job["id"],))
            conn.execute("DELETE FROM candidates WHERE job_id = %s", (job["id"],))
            conn.execute("DELETE FROM jobs WHERE id = %s", (job["id"],))
            conn.commit()

    def _of_job(self, client, job_id, params=""):
        """เฉพาะนัดของตำแหน่งที่เทสสร้าง — ฐานข้อมูลจริงมีนัดของงานอื่นปนอยู่ได้."""
        rows = client.get(f"/api/v1/interviews{params}").json()
        return [r for r in rows if r["job_id"] == job_id]

    def test_ต้องล็อกอินก่อนดูตาราง(self, anon):
        assert anon.get("/api/v1/interviews").status_code == 401

    def test_เรียงตามเวลาและตัดคนที่ยุติหรือจ้างแล้วออก(self, client, scheduled_job):
        job_id, _ = scheduled_job
        rows = self._of_job(client, job_id)
        # "ไม่มีวันนัด" ไม่มี scheduled_at · "ยุติแล้ว" กับ "จ้างแล้ว" ถูกกรองทิ้ง
        assert [r["full_name"] for r in rows] == ["นัดวันแรก", "นัดวันที่สาม"]
        assert rows[0]["job_title"] == "เทสตารางสัมภาษณ์ (ลบได้)"
        assert rows[0]["stage"] == "scheduled"

    def test_กรองตามช่วงเวลาที่ส่งมา(self, client, scheduled_job):
        job_id, base = scheduled_job
        start = (base + timedelta(days=1)).isoformat()
        rows = self._of_job(client, job_id, f"?from={quote(start)}")
        assert [r["full_name"] for r in rows] == ["นัดวันที่สาม"]

        end = (base + timedelta(days=1)).isoformat()
        rows = self._of_job(client, job_id, f"?to={quote(end)}")
        assert [r["full_name"] for r in rows] == ["นัดวันแรก"]

    def test_นัดในอนาคตยังไม่ค้าง(self, client, scheduled_job):
        """fixture ตั้งนัดไว้ปี 2026-10 ซึ่งอยู่ข้างหน้า — ต้องไม่ขึ้นป้ายค้าง."""
        job_id, _ = scheduled_job
        assert all(r["overdue"] is False for r in self._of_job(client, job_id))

    def test_ไม่มีนัดเลยได้ลิสต์ว่างไม่ใช่_error(self, client, scheduled_job):
        """ช่วงเวลาที่ไม่มีนัดอยู่เลย — หน้าเว็บต้องได้ [] ไม่ใช่ 500."""
        job_id, base = scheduled_job
        far = (base + timedelta(days=365)).isoformat()
        r = client.get(f"/api/v1/interviews?from={quote(far)}")
        assert r.status_code == 200
        assert [x for x in r.json() if x["job_id"] == job_id] == []
