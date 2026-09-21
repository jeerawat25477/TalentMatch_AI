"""ข้อเสนอจ้างงาน (routers/job_offer.py).

รัน: docker compose exec backend python -m pytest tests/test_job_offer.py -v

สิ่งที่เทสชุดนี้กัน:
1. **ตอบรับ ≠ จ้าง** — ต้องไม่มีแถวใน employees เกิดขึ้นเอง การจ้างผ่านหน้าต่างรับเข้าเท่านั้น
2. บันทึกข้อเสนอแล้วขั้นย้ายเป็น "ยื่นข้อเสนอ" · ปฏิเสธแล้วปิดกระบวนการ — ในทรานแซกชันเดียว
3. ข้อเสนออยู่ต่อแม้ขั้นเปลี่ยน (เหตุผลของตารางแยกจาก hiring_stage)
4. **ไม่แตะ hr_decisions เด็ดขาด** — ไม่งั้นกราฟถูกปลุกให้ตัดสินใหม่และเผาโควตา
5. หน้ารายละเอียดของคนที่ไม่มีข้อเสนอได้ null ไม่ใช่ 500
"""
import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_conn
from app.main import app
from app.routers.job_offer import _next_stage_after_offer, _stage_after_response

OFFER = {
    "position": "AI Engineer",
    "salary": "45000",
    "start_date": "2026-11-01",
    "respond_by": "2026-10-01",
    "note": "โบนัสตามผลงาน",
}


# ---------- กฎการย้ายขั้น (ฟังก์ชันบริสุทธิ์ ไม่ต่อ DB) ----------


class TestNextStageAfterOffer:
    @pytest.mark.parametrize("current", [None, "invited", "scheduled", "interviewed"])
    def test_ยังไม่ถึงขั้นยื่นข้อเสนอ_เลื่อนขึ้นมาให้(self, current):
        assert _next_stage_after_offer(current) == "offer"

    def test_อยู่ขั้นยื่นข้อเสนอแล้ว_ไม่แตะ_moved_at_ขยับเปล่า(self):
        assert _next_stage_after_offer("offer") is None

    def test_การ์ดที่พักไว้ต้องไม่ถูกปลุกด้วยการแก้ข้อเสนอ(self):
        assert _next_stage_after_offer("declined") is None


class TestStageAfterResponse:
    def test_ปฏิเสธแล้วปิดกระบวนการ(self):
        assert _stage_after_response("declined", "offer") == "declined"
        assert _stage_after_response("declined", "declined") is None

    def test_ตอบรับแล้วขั้นไม่เปลี่ยน_เพราะยังไม่ได้จ้าง(self):
        assert _stage_after_response("accepted", "offer") is None

    def test_กดปฏิเสธผิดแล้วแก้เป็นตอบรับ_ดึงกลับไปขั้นยื่นข้อเสนอ(self):
        assert _stage_after_response("accepted", "declined") == "offer"


# ---------- endpoint (ใช้ DB จริงในคอนเทนเนอร์) ----------


@pytest.fixture
def anon() -> TestClient:
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: "admin-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def interviewed():
    """ผู้สมัครที่ผ่านคัดกรองและสัมภาษณ์แล้ว — จุดเริ่มปกติของการยื่นข้อเสนอ."""
    with get_conn() as conn:
        job = conn.execute(
            "INSERT INTO jobs (title, raw_text) VALUES (%s, %s) RETURNING id",
            ("เทสข้อเสนอ (ลบได้)", "ต้องมี Python"),
        ).fetchone()
        cand = conn.execute(
            "INSERT INTO candidates (job_id, full_name) VALUES (%s, %s) RETURNING id",
            (job["id"], "ผู้สมัครข้อเสนอ"),
        ).fetchone()
        conn.execute(
            "INSERT INTO evaluations (job_id, candidate_id, fit_score) VALUES (%s, %s, 85)",
            (job["id"], cand["id"]),
        )
        conn.execute(
            "INSERT INTO hr_decisions (candidate_id, decision) VALUES (%s, 'approved')",
            (cand["id"],),
        )
        conn.execute(
            "INSERT INTO hiring_stage (candidate_id, stage) VALUES (%s, 'interviewed')",
            (cand["id"],),
        )
        conn.commit()
    yield str(job["id"]), str(cand["id"])
    with get_conn() as conn:
        conn.execute("DELETE FROM employees WHERE candidate_id = %s", (cand["id"],))
        conn.execute("DELETE FROM candidates WHERE id = %s", (cand["id"],))
        conn.execute("DELETE FROM jobs WHERE id = %s", (job["id"],))
        conn.commit()


def _stage(cid: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT stage FROM hiring_stage WHERE candidate_id = %s", (cid,)
        ).fetchone()
    return row["stage"] if row else None


def _count(table: str, cid: str) -> int:
    with get_conn() as conn:
        return conn.execute(
            f"SELECT count(*) AS n FROM {table} WHERE candidate_id = %s", (cid,)
        ).fetchone()["n"]


class TestAuthGate:
    def test_ต้องล็อกอินก่อนบันทึกข้อเสนอ(self, anon, interviewed):
        _, cid = interviewed
        assert anon.put(f"/api/v1/candidates/{cid}/offer", json=OFFER).status_code == 401

    def test_ต้องล็อกอินก่อนบันทึกคำตอบ(self, anon, interviewed):
        _, cid = interviewed
        r = anon.post(f"/api/v1/candidates/{cid}/offer/response", json={"response": "accepted"})
        assert r.status_code == 401


class TestUpsertOffer:
    def test_บันทึกแล้วย้ายขั้นเป็นยื่นข้อเสนอ(self, client, interviewed):
        _, cid = interviewed
        r = client.put(f"/api/v1/candidates/{cid}/offer", json=OFFER)
        assert r.status_code == 200
        body = r.json()
        assert body["position"] == "AI Engineer"
        assert float(body["salary"]) == 45000
        assert body["response"] == "pending"
        assert body["offered_at"] is not None
        assert _stage(cid) == "offer"

    def test_หน้ารายละเอียดเห็นข้อเสนอ(self, client, interviewed):
        _, cid = interviewed
        client.put(f"/api/v1/candidates/{cid}/offer", json=OFFER)
        detail = client.get(f"/api/v1/candidates/{cid}").json()
        assert detail["offer"]["position"] == "AI Engineer"
        assert detail["offer"]["respond_by"] == "2026-10-01"
        assert detail["board_stage"] == "offer"

    def test_ไม่มีข้อเสนอได้_null_ไม่ใช่_500(self, client, interviewed):
        _, cid = interviewed
        r = client.get(f"/api/v1/candidates/{cid}")
        assert r.status_code == 200 and r.json()["offer"] is None

    def test_แก้ข้อเสนอหลังตอบแล้ว_คำตอบกลับเป็นรอคำตอบ(self, client, interviewed):
        """ต่อรองใหม่ = ข้อเสนอฉบับใหม่ คำตอบของฉบับเก่าใช้ไม่ได้แล้ว."""
        _, cid = interviewed
        first = client.put(f"/api/v1/candidates/{cid}/offer", json=OFFER).json()
        client.post(
            f"/api/v1/candidates/{cid}/offer/response",
            json={"response": "declined", "decline_reason": "เงินเดือนไม่ถึง"},
        )
        r = client.put(
            f"/api/v1/candidates/{cid}/offer", json={**OFFER, "salary": "50000"}
        ).json()
        assert r["response"] == "pending"
        assert r["responded_at"] is None and r["decline_reason"] is None
        assert float(r["salary"]) == 50000
        assert r["offered_at"] == first["offered_at"]   # เวลายื่นครั้งแรกคงไว้

    def test_เงินเดือนติดลบต้อง_422(self, client, interviewed):
        _, cid = interviewed
        r = client.put(f"/api/v1/candidates/{cid}/offer", json={**OFFER, "salary": "-1"})
        assert r.status_code == 422

    def test_ไม่ใส่ตำแหน่งต้อง_422(self, client, interviewed):
        _, cid = interviewed
        r = client.put(f"/api/v1/candidates/{cid}/offer", json={**OFFER, "position": ""})
        assert r.status_code == 422

    def test_ไม่พบผู้สมัครต้อง_404(self, client):
        missing = "11111111-1111-1111-1111-111111111111"
        assert client.put(f"/api/v1/candidates/{missing}/offer", json=OFFER).status_code == 404

    def test_จ้างแล้วต้อง_409(self, client, interviewed):
        job_id, cid = interviewed
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO employees (candidate_id, job_id, full_name, position)
                   VALUES (%s, %s, %s, %s)""",
                (cid, job_id, "ผู้สมัครข้อเสนอ", "AI Engineer"),
            )
            conn.commit()
        assert client.put(f"/api/v1/candidates/{cid}/offer", json=OFFER).status_code == 409

    def test_การ์ดที่พักไว้_บันทึกข้อเสนอแล้วขั้นไม่ถูกปลุก(self, client, interviewed):
        _, cid = interviewed
        with get_conn() as conn:
            conn.execute(
                "UPDATE hiring_stage SET stage = 'declined' WHERE candidate_id = %s", (cid,)
            )
            conn.commit()
        client.put(f"/api/v1/candidates/{cid}/offer", json=OFFER)
        assert _stage(cid) == "declined"


class TestOfferResponse:
    def test_ตอบรับแล้ว_ไม่มีระเบียนพนักงานเกิดเอง(self, client, interviewed):
        """หัวใจของชุดนี้: การจ้างเป็นระเบียนถาวร ต้องผ่านหน้าต่างที่ HR กดยืนยันเท่านั้น."""
        _, cid = interviewed
        client.put(f"/api/v1/candidates/{cid}/offer", json=OFFER)
        r = client.post(f"/api/v1/candidates/{cid}/offer/response", json={"response": "accepted"})
        assert r.status_code == 200
        assert r.json()["response"] == "accepted"
        assert r.json()["responded_at"] is not None
        assert _count("employees", cid) == 0
        assert _stage(cid) == "offer"   # ยังไม่ได้จ้าง ขั้นไม่เปลี่ยน

    def test_ปฏิเสธแล้วปิดกระบวนการพร้อมเก็บเหตุผล(self, client, interviewed):
        _, cid = interviewed
        client.put(f"/api/v1/candidates/{cid}/offer", json=OFFER)
        r = client.post(
            f"/api/v1/candidates/{cid}/offer/response",
            json={"response": "declined", "decline_reason": "  ได้งานที่อื่น  "},
        ).json()
        assert r["response"] == "declined"
        assert r["decline_reason"] == "ได้งานที่อื่น"
        assert _stage(cid) == "declined"

    def test_ข้อเสนออยู่ต่อหลังขั้นเปลี่ยนเป็นไม่ไปต่อ(self, client, interviewed):
        """เหตุผลที่แยกตาราง — hiring_stage เปลี่ยนแล้ว แต่ร่องรอยการยื่นข้อเสนอต้องอยู่."""
        _, cid = interviewed
        client.put(f"/api/v1/candidates/{cid}/offer", json=OFFER)
        client.post(f"/api/v1/candidates/{cid}/offer/response", json={"response": "declined"})
        detail = client.get(f"/api/v1/candidates/{cid}").json()
        assert detail["board_stage"] == "declined"
        assert detail["offer"]["response"] == "declined"
        assert detail["offer"]["offered_at"] is not None

    def test_ตอบรับหลังปฏิเสธผิด_ล้างเหตุผลและดึงกลับ(self, client, interviewed):
        _, cid = interviewed
        client.put(f"/api/v1/candidates/{cid}/offer", json=OFFER)
        client.post(
            f"/api/v1/candidates/{cid}/offer/response",
            json={"response": "declined", "decline_reason": "กดผิด"},
        )
        r = client.post(
            f"/api/v1/candidates/{cid}/offer/response", json={"response": "accepted"}
        ).json()
        assert r["decline_reason"] is None
        assert _stage(cid) == "offer"

    def test_ไม่แตะคำตัดสินคัดกรองของ_hr(self, client, interviewed):
        """เขียน hr_decisions = กราฟถูกปลุกให้ตัดสินใหม่ ร่างอีเมลเอง และเผาโควตา."""
        _, cid = interviewed
        client.put(f"/api/v1/candidates/{cid}/offer", json=OFFER)
        client.post(f"/api/v1/candidates/{cid}/offer/response", json={"response": "declined"})
        with get_conn() as conn:
            row = conn.execute(
                "SELECT decision FROM hr_decisions WHERE candidate_id = %s", (cid,)
            ).fetchone()
        assert row["decision"] == "approved"

    def test_ยังไม่มีข้อเสนอต้อง_404(self, client, interviewed):
        _, cid = interviewed
        r = client.post(f"/api/v1/candidates/{cid}/offer/response", json={"response": "accepted"})
        assert r.status_code == 404

    def test_คำตอบนอกรายการต้อง_422(self, client, interviewed):
        _, cid = interviewed
        client.put(f"/api/v1/candidates/{cid}/offer", json=OFFER)
        r = client.post(f"/api/v1/candidates/{cid}/offer/response", json={"response": "pending"})
        assert r.status_code == 422


class TestCascade:
    def test_ลบผู้สมัครแล้วข้อเสนอหายตาม(self, client, interviewed):
        _, cid = interviewed
        client.put(f"/api/v1/candidates/{cid}/offer", json=OFFER)
        assert _count("job_offers", cid) == 1
        assert client.delete(f"/api/v1/candidates/{cid}").status_code == 200
        assert _count("job_offers", cid) == 0
