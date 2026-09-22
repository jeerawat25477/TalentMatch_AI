"""ทักษะที่ขาดบ่อยต่อตำแหน่งงาน (GET /jobs/{id}/skill-gaps) — ไม่ยิง LLM.

รัน: docker compose exec backend python -m pytest tests/test_skill_gaps.py -v

สิ่งที่เทสชุดนี้กัน:
1. นับเป็น "จำนวนคน" ถูก (ขาดใน 3 จาก 5 คน → 3)
2. ต้องมี/อยากได้ แยกนับ ไม่ปนกัน
3. top 10 เรียงมากไปน้อย เท่ากันเรียงตามชื่อ
4. นับภายในตำแหน่งเดียว ไม่รวมตำแหน่งอื่น
5. ยังไม่มีใครมีผล → ว่าง ไม่ error
"""
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Json

from app.auth import get_current_user
from app.database import get_conn
from app.main import app
from app.routers.jobs import _top_missing


def gap(req=(), pref=()):
    return {"matched_required": [], "missing_required": list(req),
            "matched_preferred": [], "missing_preferred": list(pref)}


def as_pairs(items):
    return [(i.skill, i.missing_count) for i in items]


class TestCounting:
    def test_ขาดในสามจากห้าคนนับเป็นสาม(self):
        gaps = [gap(["Docker"]), gap(["Docker"]), gap(["Docker", "Go"]), gap(), gap(["Go"])]
        assert as_pairs(_top_missing(gaps, "missing_required")) == [("Docker", 3), ("Go", 2)]

    def test_ต้องมีกับอยากได้ไม่ปนกัน(self):
        gaps = [gap(req=["Docker"], pref=["Kubernetes"]), gap(pref=["Docker"])]
        assert as_pairs(_top_missing(gaps, "missing_required")) == [("Docker", 1)]
        assert as_pairs(_top_missing(gaps, "missing_preferred")) == [
            ("Docker", 1), ("Kubernetes", 1),
        ]

    def test_ชื่อซ้ำในคนเดียวนับครั้งเดียว(self):
        assert as_pairs(_top_missing([gap(["Go", "Go"])], "missing_required")) == [("Go", 1)]

    def test_เอาแค่สิบอันดับ_เรียงมากไปน้อย_เท่ากันเรียงตามชื่อ(self):
        # 12 คน: คนที่ k ขาด S00..S(11-k) → S00 ขาด 12 คน ... S11 ขาด 1 คน
        # และ 5 คนแรกขาด B กับ A → เสมอกับ S07 ที่ 5 คน
        gaps = [
            gap([f"S{i:02d}" for i in range(12 - k)] + (["B", "A"] if k < 5 else []))
            for k in range(12)
        ]
        got = as_pairs(_top_missing(gaps, "missing_required"))
        assert len(got) == 10
        counts = [n for _, n in got]
        assert counts == sorted(counts, reverse=True)
        assert got[0] == ("S00", 12)
        assert [s for s, n in got if n == 5] == ["A", "B", "S07"]

    def test_ไม่มีผลเลยได้ว่าง(self):
        assert _top_missing([], "missing_required") == []

    def test_ข้อมูลเพี้ยนไม่พัง(self):
        gaps = [{}, {"missing_required": None}, gap(["", "  ", "Go"])]
        assert as_pairs(_top_missing(gaps, "missing_required")) == [("Go", 1)]


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: "admin-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def make_job():
    ids = []

    def _make():
        with get_conn() as conn:
            jid = conn.execute(
                "INSERT INTO jobs (title, raw_text) VALUES ('เทสทักษะที่ขาด (ลบได้)', 'x') RETURNING id"
            ).fetchone()["id"]
            conn.commit()
        ids.append(jid)
        return str(jid)

    yield _make
    with get_conn() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ANY(%s)", (ids,))
        conn.commit()


def add(job_id, g):
    """g=None = ผู้สมัครที่ยังไม่มีผล (ไม่มีแถว evaluations)."""
    with get_conn() as conn:
        cid = conn.execute(
            "INSERT INTO candidates (job_id, full_name) VALUES (%s, 'เทส') RETURNING id",
            (job_id,),
        ).fetchone()["id"]
        if g is not None:
            conn.execute(
                """INSERT INTO evaluations (job_id, candidate_id, fit_score, gap_analysis)
                   VALUES (%s, %s, 50, %s)""",
                (job_id, cid, Json(g)),
            )
        conn.commit()


def url(job_id):
    return f"/api/v1/jobs/{job_id}/skill-gaps"


class TestEndpoint:
    def test_ต้องล็อกอินก่อน(self, make_job):
        assert TestClient(app).get(url(make_job())).status_code == 401

    def test_ไม่มีใครมีผลได้ว่างไม่_error(self, client, make_job):
        job = make_job()
        add(job, None)
        assert client.get(url(job)).json() == {
            "required": [], "preferred": [], "total_candidates": 0,
        }

    def test_นับภายในตำแหน่งเดียว(self, client, make_job):
        job, other = make_job(), make_job()
        for g in [gap(["Docker"], ["AWS"]), gap(["Docker"]), gap(["Docker", "Go"]), gap(), gap(["Go"])]:
            add(job, g)
        add(other, gap(["Docker"]))  # ตำแหน่งอื่น ห้ามนับรวม
        body = client.get(url(job)).json()
        assert body["total_candidates"] == 5
        assert body["required"] == [
            {"skill": "Docker", "missing_count": 3},
            {"skill": "Go", "missing_count": 2},
        ]
        assert body["preferred"] == [{"skill": "AWS", "missing_count": 1}]

    def test_ไม่พบตำแหน่งงาน_404(self, client):
        assert client.get(url("00000000-0000-0000-0000-000000000000")).status_code == 404
