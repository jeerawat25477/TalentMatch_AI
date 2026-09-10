"""ตัดสินหลายคนพร้อมกัน — ต้องเป็น partial success เสมอ.

หัวใจของเทสชุดนี้: ถ้าคนหนึ่งใน 10 มีปัญหา (ไม่พบ / กำลังประมวลผลอยู่) แล้วทำให้อีก 9 คน
ที่ควรสำเร็จพลอยไม่ได้ทำไปด้วย จะแย่กว่าไม่มี bulk action เลย — จึงห้ามโยน exception
และต้องรายงานว่าใครถูกข้ามเพราะอะไร

⚠️ ไฟล์นี้แตะ DB จริงและ monkeypatch ตัวเดินกราฟไม่ให้ยิง LLM (โควตาฟรี 20 call/วัน)
รัน: docker compose exec backend python -m pytest tests/test_bulk_decision.py -v
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.agents.runner import active_candidates, release_candidate
from app.auth import get_current_user
from app.database import get_conn
from app.main import app
from app.routers import hr
from app.routers.hr import MAX_BULK_DECISION, _bulk_partition

URL = "/api/v1/candidates/bulk-decision"
MISSING = str(uuid.uuid4())


class TestBulkPartition:
    """กฎการคัดกรอง — ฟังก์ชันบริสุทธิ์ ไม่ต้องมี DB."""

    def test_ปนกันทุกแบบในคำขอเดียว(self):
        ok1, ok2, busy, gone = "a", "b", "c", "d"
        accepted, skipped = _bulk_partition(
            [ok1, busy, gone, ok2, ok1], existing={ok1, ok2, busy}, active=frozenset({busy})
        )
        assert accepted == [ok1, ok2]
        reasons = {s["id"]: s["reason"] for s in skipped}
        assert reasons[busy] == "กำลังประมวลผลอยู่"
        assert reasons[gone] == "ไม่พบผู้สมัคร"
        # ส่ง id เดิมมาสองครั้ง ต้องนับครั้งเดียว ไม่ใช่เดินกราฟซ้ำ
        assert sum(1 for s in skipped if s["reason"] == "ส่งชื่อซ้ำในคำขอเดียวกัน") == 1

    def test_ทุกคนถูกข้ามก็ไม่โยน_exception(self):
        accepted, skipped = _bulk_partition(["x"], existing=set(), active=frozenset())
        assert accepted == []
        assert len(skipped) == 1

    def test_ว่างเปล่าได้ผลว่าง(self):
        assert _bulk_partition([], existing=set(), active=frozenset()) == ([], [])

    def test_คนที่พร้อมทั้งหมดผ่านหมด(self):
        accepted, skipped = _bulk_partition(
            ["a", "b"], existing={"a", "b"}, active=frozenset()
        )
        assert accepted == ["a", "b"] and skipped == []


@pytest.fixture
def anon() -> TestClient:
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: "admin-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def ran(monkeypatch) -> list:
    """ดักการ "เข้าคิว" แทนการเดินกราฟ — endpoint ไม่เรียก LLM เองอีกแล้ว.

    ตั้งแต่ย้ายไปใช้ processing_queue เราเตอร์แค่ INSERT แถวคิวแล้วตอบกลับ ส่วนการ
    เดินกราฟเป็นหน้าที่ของ queue_worker เทสชุดนี้จึงตรวจว่า "ใครถูกส่งเข้าคิวบ้าง
    พร้อมคำตัดสินอะไร" ซึ่งเป็นสิ่งเดียวที่ endpoint นี้รับผิดชอบจริง ๆ

    ต้อง release เองเพราะตัวจริงปลดจองตอน worker รันจบ (ในเทสไม่มี worker)
    """
    calls: list[tuple] = []

    def fake(rows):
        for cid, _job, kind, payload in rows:
            assert kind == "resume_after_decision"
            calls.append((str(cid), payload["decision"], payload.get("notes")))
            release_candidate(str(cid))

    monkeypatch.setattr(hr, "enqueue_many", fake)
    return calls


@pytest.fixture
def two_candidates():
    """สร้างตำแหน่งงาน + ผู้สมัคร 2 คนของตัวเอง แล้วลบทิ้ง — ไม่แตะข้อมูลจริง."""
    with get_conn() as conn:
        job = conn.execute(
            "INSERT INTO jobs (title, raw_text) VALUES (%s, %s) RETURNING id",
            ("เทส bulk (ลบได้)", "x"),
        ).fetchone()
        ids = [
            str(
                conn.execute(
                    "INSERT INTO candidates (job_id, full_name) VALUES (%s, %s) RETURNING id",
                    (job["id"], f"ผู้สมัครเทส {i}"),
                ).fetchone()["id"]
            )
            for i in range(2)
        ]
        conn.commit()
    yield ids
    with get_conn() as conn:  # candidates/hr_decisions cascade ตาม job
        conn.execute("DELETE FROM jobs WHERE id = %s", (job["id"],))
        conn.commit()
    for cid in ids:
        release_candidate(cid)


class TestAuthGate:
    def test_ต้องล็อกอินก่อน(self, anon):
        r = anon.post(URL, json={"candidate_ids": [MISSING], "decision": "approved"})
        assert r.status_code == 401


class TestValidation:
    def test_เกินเพดานต้อง_413(self, client):
        ids = [str(uuid.uuid4()) for _ in range(MAX_BULK_DECISION + 1)]
        r = client.post(URL, json={"candidate_ids": ids, "decision": "approved"})
        assert r.status_code == 413
        assert str(MAX_BULK_DECISION) in r.json()["detail"]

    def test_รายชื่อว่างต้อง_422(self, client):
        assert client.post(URL, json={"candidate_ids": [], "decision": "approved"}).status_code == 422

    @pytest.mark.parametrize("decision", ["pending", "APPROVED", "", "hired"])
    def test_คำตัดสินนอกเหนือที่กำหนดต้อง_422(self, client, decision):
        r = client.post(URL, json={"candidate_ids": [MISSING], "decision": decision})
        assert r.status_code == 422


class TestPartialSuccess:
    def test_ไม่พบทุกคนก็ยัง_202_ไม่ใช่_error(self, client, ran):
        r = client.post(URL, json={"candidate_ids": [MISSING], "decision": "approved"})
        assert r.status_code == 202
        body = r.json()
        assert body["accepted"] == 0
        assert body["skipped"][0]["reason"] == "ไม่พบผู้สมัคร"
        assert ran == []  # ไม่มีใครถูกสั่งเดินกราฟ = ไม่เปลือง LLM

    def test_คนที่มีจริงผ่าน_คนที่ไม่มีถูกข้าม(self, client, ran, two_candidates):
        ok, other = two_candidates
        r = client.post(
            URL,
            json={"candidate_ids": [ok, MISSING, other], "decision": "approved", "notes": "ผ่านรอบแรก"},
        )
        assert r.status_code == 202
        body = r.json()
        assert body["accepted"] == 2
        assert set(body["candidate_ids"]) == {ok, other}
        assert [s["id"] for s in body["skipped"]] == [MISSING]

        # เดินกราฟให้เฉพาะคนที่รับเข้าคิว พร้อม notes เดียวกันทั้งชุด
        assert {c[0] for c in ran} == {ok, other}
        assert all(c[1:] == ("approved", "ผ่านรอบแรก") for c in ran)

        # คำตัดสินถูกบันทึกลง DB จริง
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT candidate_id, decision, notes FROM hr_decisions WHERE candidate_id = ANY(%s)",
                ([ok, other],),
            ).fetchall()
        assert len(rows) == 2
        assert all(r["decision"] == "approved" and r["notes"] == "ผ่านรอบแรก" for r in rows)

    def test_คนที่กำลังประมวลผลอยู่ถูกข้าม(self, client, ran, two_candidates, monkeypatch):
        busy, free = two_candidates
        monkeypatch.setattr(hr, "active_candidates", lambda: frozenset({busy}))
        r = client.post(URL, json={"candidate_ids": [busy, free], "decision": "rejected"})
        body = r.json()
        assert body["accepted"] == 1 and body["candidate_ids"] == [free]
        assert body["skipped"] == [{"id": busy, "reason": "กำลังประมวลผลอยู่"}]
        assert {c[0] for c in ran} == {free}

    def test_ไม่ทิ้งคนค้างในทะเบียนหลังจบ(self, client, ran, two_candidates):
        ok, other = two_candidates
        client.post(URL, json={"candidate_ids": [ok, other], "decision": "approved"})
        # ตัวจริงปลดจองตอน worker รันจบ (runner.decide_candidate ปลดใน finally)
        assert not ({ok, other} & set(active_candidates()))

    def test_เข้าคิวจริงลง_db_พร้อมคำตัดสิน(self, client, two_candidates):
        """ไม่ mock อะไรเลย — พิสูจน์ว่าแถวคิวถูกสร้างจริง ไม่ใช่แค่ตอบ 202 เปล่า ๆ.

        นี่คือสิ่งที่ทำให้งานไม่หายตอนรีสตาร์ต: คำสั่งอยู่ใน DB ไม่ใช่ในหน่วยความจำ
        """
        ok, other = two_candidates
        client.post(
            URL,
            json={"candidate_ids": [ok, other], "decision": "rejected", "notes": "ไม่ตรงสาย"},
        )
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT candidate_id, kind, status, payload FROM processing_queue
                    WHERE candidate_id = ANY(%s)""",
                ([ok, other],),
            ).fetchall()
        assert len(rows) == 2
        assert all(r["kind"] == "resume_after_decision" for r in rows)
        assert all(r["status"] == "queued" for r in rows)
        assert all(r["payload"] == {"decision": "rejected", "notes": "ไม่ตรงสาย"} for r in rows)
        for cid in (ok, other):
            release_candidate(cid)
