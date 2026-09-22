"""ฮิสโตแกรมกระจายคะแนนต่อตำแหน่งงาน (GET /jobs/{id}/score-distribution) — ไม่ยิง LLM.

รัน: docker compose exec backend python -m pytest tests/test_score_distribution.py -v

สิ่งที่เทสชุดนี้กัน:
1. นับเข้าช่วงถูก — 100 พอดีต้องอยู่ช่วง 90 ไม่ตกขอบเป็นช่วงที่ 11
2. นับเฉพาะคนที่มีคะแนนแล้ว (คนที่ยังรอคิวไม่มีแถว evaluations)
3. ยังไม่มีใครมีคะแนน → ทุกช่วงเป็น 0 total=0 ไม่ error
4. เส้นแบ่งมาจาก bands.py ไม่ใช่เลขที่เขียนซ้ำ
"""
import pytest
from fastapi.testclient import TestClient

from app.agents import bands
from app.auth import get_current_user
from app.database import get_conn
from app.main import app
from app.routers.jobs import _score_buckets


def counts(scores):
    return [b.count for b in _score_buckets(scores)]


class TestBuckets:
    def test_มีสิบช่วงเริ่มที่ศูนย์ห่างกันสิบ(self):
        assert [b.range_start for b in _score_buckets([])] == list(range(0, 100, 10))

    def test_คะแนนร้อยพอดีเข้าช่วงสุดท้าย(self):
        assert counts([100]) == [0] * 9 + [1]

    def test_ขอบล่างของช่วงนับเข้าช่วงนั้น(self):
        # 0→ช่วง 0, 9→ช่วง 0, 10→ช่วง 10, 50→ช่วง 50, 70→ช่วง 70, 99→ช่วง 90
        assert counts([0, 9, 10, 50, 70, 99]) == [2, 1, 0, 0, 0, 1, 0, 1, 0, 1]

    def test_ไม่มีคะแนนเลยได้ศูนย์ทุกช่วง(self):
        assert counts([]) == [0] * 10


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: "admin-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def job():
    with get_conn() as conn:
        jid = conn.execute(
            "INSERT INTO jobs (title, raw_text) VALUES ('เทสกระจายคะแนน (ลบได้)', 'x') RETURNING id"
        ).fetchone()["id"]
        conn.commit()
    yield str(jid)
    with get_conn() as conn:
        conn.execute("DELETE FROM jobs WHERE id = %s", (jid,))
        conn.commit()


def add_candidate(job_id: str, score: int | None) -> None:
    """score=None = ผู้สมัครที่ยังไม่มีผล (ไม่มีแถว evaluations)."""
    with get_conn() as conn:
        cid = conn.execute(
            "INSERT INTO candidates (job_id, full_name) VALUES (%s, 'เทส') RETURNING id",
            (job_id,),
        ).fetchone()["id"]
        if score is not None:
            conn.execute(
                "INSERT INTO evaluations (job_id, candidate_id, fit_score) VALUES (%s, %s, %s)",
                (job_id, cid, score),
            )
        conn.commit()


def url(job_id: str) -> str:
    return f"/api/v1/jobs/{job_id}/score-distribution"


class TestEndpoint:
    def test_ต้องล็อกอินก่อน(self, job):
        assert TestClient(app).get(url(job)).status_code == 401

    def test_ไม่มีใครมีคะแนนได้ศูนย์ไม่_error(self, client, job):
        add_candidate(job, None)  # รอคิวอยู่ ยังไม่มีผล
        body = client.get(url(job)).json()
        assert body["total"] == 0
        assert [b["count"] for b in body["buckets"]] == [0] * 10

    def test_นับเฉพาะคนที่มีคะแนนแล้ว(self, client, job):
        for s in (100, 95, 72, 70, 55, 20, None, None):
            add_candidate(job, s)
        body = client.get(url(job)).json()
        assert body["total"] == 6
        assert [b["count"] for b in body["buckets"]] == [0, 0, 1, 0, 0, 1, 0, 2, 0, 2]

    def test_เส้นแบ่งมาจาก_bands(self, client, job):
        body = client.get(url(job)).json()
        assert body["auto_advance_above"] == bands.AUTO_ADVANCE_ABOVE
        assert body["review_from"] == bands.REVIEW_FROM

    def test_ไม่พบตำแหน่งงาน_404(self, client):
        assert client.get(url("00000000-0000-0000-0000-000000000000")).status_code == 404
