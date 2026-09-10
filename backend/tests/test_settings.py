"""เราเตอร์ค่าตั้งค่า + สวิตช์ปากทางรับอีเมล (app.routers.settings, app.settings).

รัน: docker compose exec backend python -m pytest tests/test_settings.py -v

สิ่งที่เทสชุดนี้กัน:
1. สวิตช์ต้องมีผลทันที — กด PATCH แล้ว GET ตามต้องเห็นค่าใหม่ ไม่ติดแคช
   (ถ้าติด HR จะกดแล้วคิดว่าปุ่มเสีย แล้วกดซ้ำ)
2. **response ต้องไม่มีความลับของ IMAP หลุดออกไป** — บอกได้แค่ว่าตั้งค่าครบไหม
3. ดีฟอลต์ต้องเป็น "ปิด" เสมอ
4. ตัวนับรายวันต้องนับเฉพาะของวันนี้ ไม่ลากของเมื่อวานมารวม
"""
import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_conn
from app.email_intake import DEFAULT_SETTING, SETTING_KEY
from app.main import app
from app.settings import get_setting, invalidate, patch_setting, set_setting

URL = "/api/v1/settings/email-intake"


@pytest.fixture(autouse=True)
def restore_setting():
    """คืนค่าสวิตช์เป็นค่าเดิมหลังทุกเทส — ห้ามทิ้งไว้เปิดค้าง."""
    invalidate()
    before = dict(get_setting(SETTING_KEY, DEFAULT_SETTING))
    yield
    set_setting(SETTING_KEY, before)
    invalidate()


@pytest.fixture
def anon() -> TestClient:
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: "admin-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestAuthGate:
    def test_ต้องล็อกอินก่อนอ่านสถานะ(self, anon):
        assert anon.get(URL).status_code == 401

    def test_ต้องล็อกอินก่อนกดสวิตช์(self, anon):
        assert anon.patch(URL, json={"enabled": True}).status_code == 401


class TestToggle:
    def test_ดีฟอลต์ต้องเป็นปิด(self, client):
        set_setting(SETTING_KEY, dict(DEFAULT_SETTING))
        assert client.get(URL).json()["enabled"] is False

    def test_เปิดแล้วเห็นผลทันทีไม่ติดแคช(self, client):
        """แคชค่าตั้งค่ามี TTL 10 วิ ถ้า set_setting ไม่ล้างแคช เทสนี้จะพัง."""
        client.patch(URL, json={"enabled": False})
        assert client.patch(URL, json={"enabled": True}).json()["enabled"] is True
        assert client.get(URL).json()["enabled"] is True   # GET ตามมาทันที

    def test_ปิดกลับได้(self, client):
        client.patch(URL, json={"enabled": True})
        assert client.patch(URL, json={"enabled": False}).json()["enabled"] is False
        assert client.get(URL).json()["enabled"] is False

    def test_กดสวิตช์ต้องไม่ล้าง_last_uid_seen(self, client):
        """ถ้าเขียนทับทั้งก้อน รอบถัดไปจะดูดเมลทั้งกล่องซ้ำแล้วเสียโควตายกกล่อง."""
        patch_setting(SETTING_KEY, {"last_uid_seen": "42"}, DEFAULT_SETTING)
        client.patch(URL, json={"enabled": True})
        assert get_setting(SETTING_KEY, DEFAULT_SETTING)["last_uid_seen"] == "42"

    @pytest.mark.parametrize("body", [{}, {"enabled": "ใช่"}, {"enabled": None}])
    def test_ค่าที่ไม่ใช่_bool_ต้อง_422(self, client, body):
        assert client.patch(URL, json=body).status_code == 422


class TestNoSecretLeak:
    def test_response_ต้องไม่มีความลับของ_imap(self, client):
        """รหัสผ่านและโฮสต์อ่านจาก env เท่านั้น ห้ามวิ่งผ่าน API ไม่ว่าทางไหน.

        ⚠️ เดิมเทสนี้ห้ามอักขระ "@" ทั้ง response ซึ่งกว้างเกินไป — ตั้งแต่มี
        apply_address_template ที่อยู่รับสมัครต้องโผล่ในนี้ได้ เพราะมันคือสิ่งที่จะถูก
        ประกาศให้ผู้สมัครส่งเมลเข้ามาอยู่แล้ว ไม่ใช่ความลับ · สิ่งที่ยังห้ามเด็ดขาด
        คือรหัสผ่านและที่อยู่เซิร์ฟเวอร์ IMAP
        """
        body = client.get(URL).json()
        assert set(body) == {
            "enabled", "imap_configured", "last_poll_at", "last_error",
            "matched_count_today", "unmatched_count_today", "apply_address_template",
        }
        assert isinstance(body["imap_configured"], bool)
        blob = str(body).lower()
        for banned in ("password", "imap_host", "imap.", "993"):
            assert banned not in blob

    def test_ที่อยู่รับสมัครต้องมาจาก_imap_user_แหล่งเดียว(self, monkeypatch):
        """ถ้าหน้าเว็บโชว์กล่องหนึ่งแต่ worker ดึงอีกกล่อง ใบสมัครจะหายเงียบ."""
        from app import email_intake

        monkeypatch.setattr(email_intake, "IMAP_USER", "recruit@company.com")
        assert email_intake.apply_address_template() == "recruit+{job_id}@company.com"

    @pytest.mark.parametrize("bad_user", ["", "ไม่มีแอท", "@nolocal.com", "nolocal@"])
    def test_imap_user_ไม่สมบูรณ์ต้องคืน_none_ไม่ใช่ที่อยู่พิการ(self, monkeypatch, bad_user):
        """หน้าเว็บจะได้ซ่อนบล็อกนั้น ดีกว่าโชว์ที่อยู่ที่ส่งไปแล้วไม่ถึงใคร."""
        from app import email_intake

        monkeypatch.setattr(email_intake, "IMAP_USER", bad_user)
        assert email_intake.apply_address_template() is None

    def test_ที่อยู่รับสมัครต้องไม่มีรหัสผ่านปน(self, monkeypatch):
        from app import email_intake

        monkeypatch.setattr(email_intake, "IMAP_USER", "recruit@company.com")
        monkeypatch.setattr(email_intake, "IMAP_PASSWORD", "hunter2")
        assert "hunter2" not in (email_intake.apply_address_template() or "")

    def test_ส่ง_credential_มาก็ต้องไม่ถูกรับไว้(self, client):
        """ฟิลด์เกินถูกทิ้งโดย pydantic — ยืนยันว่าไม่มีทางแอบตั้งค่าลับผ่าน API."""
        client.patch(URL, json={"enabled": True, "imap_password": "hunter2"})
        assert "imap_password" not in get_setting(SETTING_KEY, DEFAULT_SETTING)


class TestCounts:
    def test_นับเฉพาะของวันนี้(self, client):
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO email_intake_log (outcome, detail, created_at) VALUES
                   ('matched',   'เทสวันนี้',  timezone('utc'::text, now())),
                   ('unmatched', 'เทสวันนี้',  timezone('utc'::text, now())),
                   ('matched',   'เทสเมื่อวาน', timezone('utc'::text, now()) - interval '2 days')"""
            )
            conn.commit()
        try:
            body = client.get(URL).json()
            assert body["matched_count_today"] >= 1
            assert body["unmatched_count_today"] >= 1
            # แถวของเมื่อวานต้องไม่ถูกนับรวม — ตรวจโดยเทียบกับจำนวนแถวของวันนี้จริง
            with get_conn() as conn:
                today_matched = conn.execute(
                    """SELECT count(*) AS n FROM email_intake_log
                        WHERE outcome = 'matched'
                          AND created_at >= date_trunc('day', timezone('utc'::text, now()))"""
                ).fetchone()["n"]
            assert body["matched_count_today"] == today_matched
        finally:
            with get_conn() as conn:
                conn.execute(
                    "DELETE FROM email_intake_log WHERE detail IN ('เทสวันนี้', 'เทสเมื่อวาน')"
                )
                conn.commit()


class TestSettingsHelper:
    def test_patch_แก้เฉพาะฟิลด์ที่ส่งมา(self):
        set_setting("เทสคีย์", {"a": 1, "b": 2})
        try:
            assert patch_setting("เทสคีย์", {"b": 99}) == {"a": 1, "b": 99}
        finally:
            with get_conn() as conn:
                conn.execute("DELETE FROM app_settings WHERE key = %s", ("เทสคีย์",))
                conn.commit()
            invalidate("เทสคีย์")

    def test_คีย์ที่ไม่มีคืนค่าดีฟอลต์(self):
        assert get_setting("ไม่มีคีย์นี้แน่นอน", {"ok": True}) == {"ok": True}
