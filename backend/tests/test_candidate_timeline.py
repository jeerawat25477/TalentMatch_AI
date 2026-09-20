"""ฟิลด์เวลาบน CandidateDetail ที่ไทม์ไลน์ในหน้ารายละเอียดผู้สมัครใช้.

รัน: docker compose exec backend python -m pytest tests/test_candidate_timeline.py -v

สิ่งที่เทสชุดนี้กัน: **query ที่ join หลายตารางต้องไม่พังเมื่อไม่มีแถวฝั่งนั้น**
ผู้สมัครส่วนใหญ่ในระบบไม่มีทั้ง hiring_stage, interview_outcome และ employees เลย
(คนที่ถูกปฏิเสธ หรือยังวิเคราะห์ไม่เสร็จ) — ทุกฟิลด์ต้องเป็น null เฉย ๆ ไม่ใช่ 500
บทเรียนเดิมจาก to_jsonb(io) บน LEFT JOIN ที่ไม่แมตช์ ซึ่งคืน dict ที่มี key ครบแต่ค่า
เป็น null แล้วกลายเป็น 500 ของเกือบทุกคนในระบบ
"""
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_conn
from app.main import app

# ฟิลด์เวลาทั้งหมดที่ไทม์ไลน์อ่าน — คนที่ยังไม่เริ่มกระบวนการต้องได้ null ทุกตัว
TIMELINE_FIELDS = [
    "evaluated_at",
    "hr_decided_at",
    "email_sent_at",
    "scheduled_at",
    "interview_outcome",
    "hired_at",
]


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: "admin-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def job():
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO jobs (title, raw_text) VALUES (%s, %s) RETURNING id",
            ("เทสไทม์ไลน์ (ลบได้)", "ต้องมี Python"),
        ).fetchone()
        conn.commit()
    yield str(row["id"])
    with get_conn() as conn:
        conn.execute(
            """DELETE FROM employees WHERE candidate_id IN
                 (SELECT id FROM candidates WHERE job_id = %s)""",
            (row["id"],),
        )
        conn.execute("DELETE FROM candidates WHERE job_id = %s", (row["id"],))
        conn.execute("DELETE FROM jobs WHERE id = %s", (row["id"],))
        conn.commit()


def _candidate(job_id: str, name: str) -> str:
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO candidates (job_id, full_name) VALUES (%s, %s) RETURNING id",
            (job_id, name),
        ).fetchone()
        conn.commit()
    return str(row["id"])


class TestNoProgressYet:
    """ผู้สมัครที่มีแค่ created_at — ค้างอยู่หรือยังวิเคราะห์ไม่เสร็จ."""

    def test_มีแค่เวลาสมัคร_ฟิลด์เวลาที่เหลือเป็น_null_ทั้งหมด(self, client, job):
        cid = _candidate(job, "ยังไม่มีผล")
        r = client.get(f"/api/v1/candidates/{cid}")
        assert r.status_code == 200
        body = r.json()
        assert body["created_at"] is not None
        for f in TIMELINE_FIELDS:
            assert body[f] is None, f


class TestRejectedCandidate:
    """ถูกปฏิเสธ — ไม่มีแถว hiring_stage และ interview_outcome เลย (เคสที่พบมากที่สุด)."""

    def test_มีเวลาประเมินและเวลาตัดสิน_แต่ขั้นหลังยังว่าง(self, client, job):
        cid = _candidate(job, "ถูกปฏิเสธ")
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO evaluations (job_id, candidate_id, fit_score)
                   VALUES (%s, %s, 20)""",
                (job, cid),
            )
            conn.execute(
                """INSERT INTO hr_decisions (candidate_id, decision, notes)
                   VALUES (%s, 'rejected', 'ประสบการณ์ไม่ตรง')""",
                (cid,),
            )
            conn.commit()

        body = client.get(f"/api/v1/candidates/{cid}").json()
        assert body["evaluated_at"] is not None       # เวลาที่ AI ให้คะแนน
        assert body["hr_decided_at"] is not None
        assert body["hr_decision"] == "rejected"
        # ไม่เคยถูกนัด ไม่เคยสัมภาษณ์ ไม่เคยรับเข้า — ต้องเป็น null ไม่ใช่ error
        assert body["scheduled_at"] is None
        assert body["stage_moved_at"] is None
        assert body["interview_outcome"] is None
        assert body["hired_at"] is None and body["employee_id"] is None


class TestFullPipeline:
    """เดินครบทุกขั้นจนรับเข้าเป็นพนักงาน — ทุกจุดบนไทม์ไลน์ต้องมีค่า."""

    def test_ครบทุกขั้นได้เวลาครบทุกจุด(self, client, job):
        cid = _candidate(job, "รับเข้าแล้ว")
        when = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO evaluations
                     (job_id, candidate_id, fit_score, email_sent_at, email_sent_to)
                   VALUES (%s, %s, 88, %s, %s)""",
                (job, cid, when, "somchai@example.com"),
            )
            conn.execute(
                """INSERT INTO hr_decisions (candidate_id, decision)
                   VALUES (%s, 'approved')""",
                (cid,),
            )
            conn.execute(
                """INSERT INTO hiring_stage (candidate_id, stage, scheduled_at, location)
                   VALUES (%s, 'offer', %s, %s)""",
                (cid, when, "ห้องประชุม 2"),
            )
            conn.execute(
                """INSERT INTO interview_outcome (candidate_id, result, interviewed_at)
                   VALUES (%s, 'pass', %s)""",
                (cid, date(2026, 9, 26)),
            )
            conn.execute(
                """INSERT INTO employees (candidate_id, job_id, full_name, position)
                   VALUES (%s, %s, %s, %s)""",
                (cid, job, "รับเข้าแล้ว", "AI Engineer"),
            )
            conn.commit()

        body = client.get(f"/api/v1/candidates/{cid}").json()
        for f in TIMELINE_FIELDS:
            assert body[f] is not None, f
        assert body["interview_outcome"]["result"] == "pass"
        assert body["interview_outcome"]["interviewed_at"] == "2026-09-26"
        assert body["email_sent_to"] == "somchai@example.com"
        assert body["location"] == "ห้องประชุม 2"
        assert body["employee_id"] is not None

    def test_บันทึกผลสัมภาษณ์โดยไม่ระบุวันที่ก็ยังอ่านได้(self, client, job):
        """interviewed_at ไม่บังคับ — ไทม์ไลน์ต้องรู้ว่า "สัมภาษณ์แล้ว" จากการมีผล ไม่ใช่จากวันที่."""
        cid = _candidate(job, "ไม่ระบุวันสัมภาษณ์")
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO interview_outcome (candidate_id, result) VALUES (%s, 'standby')",
                (cid,),
            )
            conn.commit()
        body = client.get(f"/api/v1/candidates/{cid}").json()
        assert body["interview_outcome"]["result"] == "standby"
        assert body["interview_outcome"]["interviewed_at"] is None
