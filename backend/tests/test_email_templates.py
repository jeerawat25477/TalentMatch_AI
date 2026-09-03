"""เทมเพลตอีเมลที่บันทึกไว้ใช้ซ้ำ — CRUD + ด่าน auth.

สองเรื่องที่เทสชุดนี้มีไว้กัน:
1. **ลืมใส่ auth ที่ระดับ router** — CLAUDE.md บอกว่าทุก endpoint ต้องผ่าน JWT ยกเว้น
   /health และ /auth/login การลืมจุดนี้คือช่องโหว่เงียบที่ไม่มีอะไรฟ้อง
2. เทมเพลตชนิดแปลกปลอมหลุดลง DB จนไปโผล่ผิดสถานการณ์ (อีเมลปฏิเสธโผล่ตอนเชิญสัมภาษณ์)

⚠️ เทสไฟล์นี้แตะ DB จริง (ต่างจากเทสอื่นที่เป็น pure function ล้วน) จึงต้องรันในคอนเทนเนอร์
และลบแถวที่สร้างทิ้งทุกครั้ง

รัน: docker compose exec backend python -m pytest tests/test_email_templates.py -v
"""
import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import app

URL = "/api/v1/email-templates"


@pytest.fixture
def anon() -> TestClient:
    """client ที่ยังไม่ได้ล็อกอิน."""
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    """client ที่ผ่าน auth แล้ว (override เฉพาะด่าน JWT ไม่แตะ logic อื่น)."""
    app.dependency_overrides[get_current_user] = lambda: "admin-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def sample() -> dict:
    return {
        "name": "เชิญสัมภาษณ์ - มาตรฐาน (เทส)",
        "kind": "invitation",
        "subject_template": "เชิญสัมภาษณ์ตำแหน่ง {job_title}",
        "body_template": "เรียน {candidate_name}\n\nขอเชิญสัมภาษณ์ครับ",
    }


class TestAuthGate:
    """ทุก path ต้องถูกกันด้วย JWT — ห้ามหลุดแม้แต่ path เดียว."""

    def test_list_ต้องล็อกอิน(self, anon):
        assert anon.get(URL).status_code == 401

    def test_create_ต้องล็อกอิน(self, anon, sample):
        assert anon.post(URL, json=sample).status_code == 401

    def test_delete_ต้องล็อกอิน(self, anon):
        r = anon.delete(f"{URL}/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 401


class TestCrud:
    def test_สร้างแล้วอ่านกลับมาได้แล้วลบได้(self, client, sample):
        created = client.post(URL, json=sample)
        assert created.status_code == 201
        body = created.json()
        tid = body["id"]
        try:
            assert body["name"] == sample["name"]
            assert body["kind"] == "invitation"
            # ข้อความต้องถูกเก็บดิบ ๆ ไม่ถูกแปลงระหว่างทาง
            assert body["body_template"] == sample["body_template"]

            listed = client.get(URL).json()
            assert tid in [t["id"] for t in listed]
        finally:
            assert client.delete(f"{URL}/{tid}").status_code == 200

        assert tid not in [t["id"] for t in client.get(URL).json()]

    def test_กรองตามชนิดได้(self, client, sample):
        inv = client.post(URL, json=sample).json()
        rej = client.post(
            URL, json={**sample, "name": "ปฏิเสธ (เทส)", "kind": "rejection"}
        ).json()
        try:
            ids = [t["id"] for t in client.get(URL, params={"kind": "invitation"}).json()]
            # เอาอีเมลปฏิเสธไปโผล่ตอนเชิญสัมภาษณ์ไม่ได้
            assert inv["id"] in ids
            assert rej["id"] not in ids
        finally:
            client.delete(f"{URL}/{inv['id']}")
            client.delete(f"{URL}/{rej['id']}")

    def test_ลบตัวที่ไม่มีได้_404(self, client):
        r = client.delete(f"{URL}/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404


class TestValidation:
    @pytest.mark.parametrize("kind", ["spam", "", "INVITATION", "approved"])
    def test_ชนิดนอกเหนือจากที่กำหนดต้องถูกปฏิเสธ(self, client, sample, kind):
        r = client.post(URL, json={**sample, "kind": kind})
        assert r.status_code == 422

    @pytest.mark.parametrize("field", ["name", "subject_template", "body_template"])
    def test_ช่องว่างเปล่าต้องถูกปฏิเสธ(self, client, sample, field):
        assert client.post(URL, json={**sample, field: ""}).status_code == 422
