"""ร่างอีเมลฉบับที่ HR แก้เอง (PUT/DELETE /candidates/{id}/email/draft).

รัน: docker compose exec backend python -m pytest tests/test_email_draft.py -v

สิ่งที่เทสชุดนี้กัน:
1. **ร่างของ HR ต้องรอดเมื่อกราฟเดินรอบใหม่** — email_draft ของ AI ถูกเขียนทับและถูก
   ตั้งเป็น NULL ได้ (agents/runner.py เมื่อ drafter ล้ม) ถ้าเก็บร่างของ HR ไว้คอลัมน์
   เดียวกัน งานที่พิมพ์เองจะหายโดยไม่มีใครรู้ นี่คือเหตุผลทั้งหมดของคอลัมน์แยก
2. บันทึก/ลบแล้วหน้ารายละเอียดต้องเห็นค่าตรงกัน
3. ยังไม่มีผลประเมิน = ไม่มีร่างให้แก้ (404 ไม่ใช่ 500)
4. endpoint ถูกกันด้วย JWT เหมือนทุกเส้นทางอื่น
"""
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Json

from app.auth import get_current_user
from app.database import get_conn
from app.main import app

DRAFT = {"subject": "เรียนเชิญสัมภาษณ์", "body": "เรียน คุณสมชาย\n\nขอเชิญสัมภาษณ์วันจันทร์"}


@pytest.fixture
def anon() -> TestClient:
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: "admin-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def evaluated():
    """ผู้สมัครที่มีผลประเมินและร่างอีเมลของ AI แล้ว."""
    with get_conn() as conn:
        job = conn.execute(
            "INSERT INTO jobs (title, raw_text) VALUES (%s, %s) RETURNING id",
            ("เทสร่างอีเมล (ลบได้)", "ต้องมี Python"),
        ).fetchone()
        cand = conn.execute(
            "INSERT INTO candidates (job_id, full_name) VALUES (%s, %s) RETURNING id",
            (job["id"], "ผู้สมัครร่างอีเมล"),
        ).fetchone()
        conn.execute(
            """INSERT INTO evaluations (job_id, candidate_id, fit_score, email_draft)
               VALUES (%s, %s, 85, %s)""",
            (job["id"], cand["id"], Json({"kind": "invitation", "subject": "ของ AI", "body": "ของ AI"})),
        )
        conn.commit()
    yield str(cand["id"])
    with get_conn() as conn:
        conn.execute("DELETE FROM candidates WHERE id = %s", (cand["id"],))
        conn.execute("DELETE FROM jobs WHERE id = %s", (job["id"],))
        conn.commit()


@pytest.fixture
def no_evaluation():
    """ผู้สมัครที่ยังวิเคราะห์ไม่เสร็จ — ไม่มีแถว evaluations เลย."""
    with get_conn() as conn:
        job = conn.execute(
            "INSERT INTO jobs (title, raw_text) VALUES (%s, %s) RETURNING id",
            ("เทสร่างอีเมล ยังไม่ประเมิน (ลบได้)", "ต้องมี Python"),
        ).fetchone()
        cand = conn.execute(
            "INSERT INTO candidates (job_id, full_name) VALUES (%s, %s) RETURNING id",
            (job["id"], "ยังไม่ประเมิน"),
        ).fetchone()
        conn.commit()
    yield str(cand["id"])
    with get_conn() as conn:
        conn.execute("DELETE FROM candidates WHERE id = %s", (cand["id"],))
        conn.execute("DELETE FROM jobs WHERE id = %s", (job["id"],))
        conn.commit()


class TestAuthGate:
    def test_ต้องล็อกอินก่อนบันทึกร่าง(self, anon, evaluated):
        assert anon.put(f"/api/v1/candidates/{evaluated}/email/draft", json=DRAFT).status_code == 401

    def test_ต้องล็อกอินก่อนลบร่าง(self, anon, evaluated):
        assert anon.delete(f"/api/v1/candidates/{evaluated}/email/draft").status_code == 401


class TestSaveDraft:
    def test_บันทึกแล้วหน้ารายละเอียดเห็นค่าเดิม(self, client, evaluated):
        r = client.put(f"/api/v1/candidates/{evaluated}/email/draft", json=DRAFT)
        assert r.status_code == 200
        assert r.json()["subject"] == DRAFT["subject"]
        assert r.json()["edited_at"] is not None

        detail = client.get(f"/api/v1/candidates/{evaluated}").json()
        assert detail["email_draft_edited"] == DRAFT
        assert detail["email_draft_edited_at"] is not None
        # ร่างของ AI ต้องไม่ถูกแตะ — ปุ่ม "กลับไปใช้ร่างของ AI" ต้องมีของให้กลับไปหา
        assert detail["email_draft"]["subject"] == "ของ AI"

    def test_บันทึกทับของเดิมได้(self, client, evaluated):
        client.put(f"/api/v1/candidates/{evaluated}/email/draft", json=DRAFT)
        again = {"subject": "แก้รอบสอง", "body": "เนื้อความใหม่"}
        client.put(f"/api/v1/candidates/{evaluated}/email/draft", json=again)
        detail = client.get(f"/api/v1/candidates/{evaluated}").json()
        assert detail["email_draft_edited"] == again

    def test_หัวข้อหรือเนื้อความว่างต้อง_422(self, client, evaluated):
        r = client.put(
            f"/api/v1/candidates/{evaluated}/email/draft",
            json={"subject": "", "body": "ก"},
        )
        assert r.status_code == 422

    def test_ยังไม่มีผลประเมินต้อง_404_ไม่ใช่_500(self, client, no_evaluation):
        r = client.put(f"/api/v1/candidates/{no_evaluation}/email/draft", json=DRAFT)
        assert r.status_code == 404

    def test_ไม่พบผู้สมัครต้อง_404(self, client):
        missing = "11111111-1111-1111-1111-111111111111"
        assert client.put(f"/api/v1/candidates/{missing}/email/draft", json=DRAFT).status_code == 404


class TestClearDraft:
    def test_ลบแล้วกลับไปใช้ร่างของ_ai(self, client, evaluated):
        client.put(f"/api/v1/candidates/{evaluated}/email/draft", json=DRAFT)
        r = client.delete(f"/api/v1/candidates/{evaluated}/email/draft")
        assert r.status_code == 200 and r.json()["cleared"] is True

        detail = client.get(f"/api/v1/candidates/{evaluated}").json()
        assert detail["email_draft_edited"] is None
        assert detail["email_draft_edited_at"] is None
        assert detail["email_draft"]["subject"] == "ของ AI"   # ของ AI ยังอยู่ครบ

    def test_ลบทั้งที่ยังไม่เคยแก้ก็ไม่พัง(self, client, evaluated):
        assert client.delete(f"/api/v1/candidates/{evaluated}/email/draft").status_code == 200


class TestSurvivesGraphRerun:
    """เหตุผลทั้งหมดของการแยกคอลัมน์ — ต้องรอดทั้งตอนกราฟเขียนทับและตอนล้างเป็น NULL."""

    def test_กราฟเขียนร่างใหม่ทับ_ร่างของ_hr_ยังอยู่(self, client, evaluated):
        client.put(f"/api/v1/candidates/{evaluated}/email/draft", json=DRAFT)
        with get_conn() as conn:
            conn.execute(
                "UPDATE evaluations SET email_draft = %s WHERE candidate_id = %s",
                (Json({"kind": "rejection", "subject": "AI รอบใหม่", "body": "AI รอบใหม่"}), evaluated),
            )
            conn.commit()
        detail = client.get(f"/api/v1/candidates/{evaluated}").json()
        assert detail["email_draft_edited"] == DRAFT
        assert detail["email_draft"]["subject"] == "AI รอบใหม่"

    def test_runner_ล้าง_email_draft_เป็น_null_ร่างของ_hr_ยังอยู่(self, client, evaluated):
        """agents/runner.py ตั้ง email_draft = NULL เมื่อเขียนคำถามสัมภาษณ์แล้ว drafter ล้ม."""
        client.put(f"/api/v1/candidates/{evaluated}/email/draft", json=DRAFT)
        with get_conn() as conn:
            conn.execute(
                "UPDATE evaluations SET email_draft = NULL WHERE candidate_id = %s",
                (evaluated,),
            )
            conn.commit()
        detail = client.get(f"/api/v1/candidates/{evaluated}").json()
        assert detail["email_draft"] is None
        assert detail["email_draft_edited"] == DRAFT
