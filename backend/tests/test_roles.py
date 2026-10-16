"""ระดับสิทธิ์ admin / demo (บัญชีทดลองให้อาจารย์และเพื่อนกดเล่น).

demo ทำได้เหมือน HR ยกเว้น ลบ · ตั้งค่าระบบ — กันที่ backend ด้วย require_admin
(ส่งอีเมลจริงได้ตั้งแต่ 2026-10-16 ตามที่ผู้ใช้เลือก — log ชื่อคนส่งทุกครั้งแทน)
หน้าเว็บซ่อนปุ่มเป็นแค่ความสะดวก คนยิง API ตรงก็ต้องโดนกันเหมือนกัน
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute

from app.auth import get_current_role, get_current_user, require_admin
from app.database import get_conn
from app.main import app
from scripts.manage_users import check_password, check_username, leaves_no_admin

# DELETE ที่ demo ทำได้: ลบแค่ร่างอีเมลที่ HR แก้เอง แล้วกลับไปใช้ร่างของ AI — ไม่มีข้อมูลหาย
DELETE_ALLOWED_FOR_DEMO = {"/api/v1/candidates/{candidate_id}/email/draft"}

# ที่ต้องกันนอกเหนือจาก DELETE
ADMIN_ONLY_NON_DELETE = {
    ("GET", "/api/v1/audit"),  # ประวัติการใช้งาน — บัญชีทดลองไม่ควรเห็นว่าคนอื่นทำอะไร
    ("PATCH", "/api/v1/settings/email-intake"),
    ("PATCH", "/api/v1/settings/screening-photos"),
}


def _calls(dependant) -> set:
    out = set()
    for d in dependant.dependencies:
        out.add(d.call)
        out |= _calls(d)
    return out


def _routes(routes=None) -> list[APIRoute]:
    """ทุก APIRoute ในแอป — FastAPI 0.14x เก็บ router ที่ include ไว้เป็น _IncludedRouter
    (มี original_router) ไม่แตกเป็น APIRoute ใน app.routes ตรง ๆ แล้ว จึงต้องไล่ลงไปเอง."""
    out: list[APIRoute] = []
    for r in app.routes if routes is None else routes:
        if isinstance(r, APIRoute):
            out.append(r)
        elif hasattr(r, "original_router"):
            out += _routes(r.original_router.routes)
    return out


def _deletes() -> set[tuple[str, str]]:
    return {
        ("DELETE", r.path)
        for r in _routes()
        if "DELETE" in r.methods and r.path not in DELETE_ALLOWED_FOR_DEMO
    }


def _guarded() -> set[tuple[str, str]]:
    return {(m, r.path) for r in _routes() if require_admin in _calls(r.dependant) for m in r.methods}


def test_every_delete_is_admin_only():
    """มีคนเพิ่ม DELETE ใหม่แล้วลืมใส่ require_admin → พังที่นี่ ก่อนบัญชีทดลองจะลบของจริงได้."""
    deletes = _deletes()
    assert len(deletes) >= 3, "หา route DELETE ไม่เจอ — วิธีไล่ route เพี้ยน (FastAPI เปลี่ยนโครงสร้าง?)"
    assert deletes <= _guarded(), f"DELETE ที่ลืมกัน: {deletes - _guarded()}"


def test_guarded_set_is_exactly_the_plan():
    """กันเกินก็ไม่ได้ — บัญชีทดลองต้องกดเล่นได้เกือบทั้งระบบ."""
    assert _guarded() == _deletes() | ADMIN_ONLY_NON_DELETE


@pytest.fixture
def as_role():
    def _set(role: str) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: f"{role}-test"
        app.dependency_overrides[get_current_role] = lambda: role
        return TestClient(app)

    yield _set
    app.dependency_overrides.pop(get_current_user, None)


RID = str(uuid.uuid4())
GUARDED_CALLS = [
    ("delete", f"/api/v1/jobs/{RID}", None),
    ("delete", f"/api/v1/candidates/{RID}", None),
    ("delete", f"/api/v1/email-templates/{RID}", None),
    ("patch", "/api/v1/settings/email-intake", {"enabled": True}),
    ("patch", "/api/v1/settings/screening-photos", {"enabled": True}),
]


@pytest.mark.parametrize("method,url,body", GUARDED_CALLS)
def test_demo_gets_403(as_role, method, url, body):
    r = getattr(as_role("demo"), method)(url, **({"json": body} if body else {}))
    assert r.status_code == 403
    assert "บัญชีทดลอง" in r.json()["detail"]


@pytest.mark.parametrize("method,url,body", GUARDED_CALLS[:3])
def test_admin_passes_the_guard(as_role, method, url, body):
    # ของที่ไม่มีอยู่จริง → handler ตอบ 404 = ผ่านด่านสิทธิ์ไปแล้ว
    assert getattr(as_role("admin"), method)(url).status_code == 404


def test_demo_can_still_play(as_role):
    """งานที่ไม่ได้ถูกกัน demo ต้องไปถึง handler (404 เพราะไม่มีของ ไม่ใช่ 403)."""
    c = as_role("demo")
    assert c.patch(f"/api/v1/jobs/{RID}", json={"status": "closed"}).status_code == 404
    assert c.post(f"/api/v1/candidates/{RID}/decision", json={"decision": "approved"}).status_code == 404


@pytest.fixture
def evaluated_candidate():
    with get_conn() as conn:
        job = conn.execute(
            "INSERT INTO jobs (title, raw_text) VALUES ('เทส role ส่งอีเมล (ลบได้)', 'Python') RETURNING id"
        ).fetchone()["id"]
        cid = conn.execute(
            "INSERT INTO candidates (job_id, full_name) VALUES (%s, 'ผู้สมัครเทส role') RETURNING id", (job,)
        ).fetchone()["id"]
        conn.execute("INSERT INTO evaluations (job_id, candidate_id, fit_score) VALUES (%s, %s, 40)", (job, cid))
        conn.commit()
    yield str(cid)
    with get_conn() as conn:
        conn.execute("DELETE FROM jobs WHERE id = %s", (job,))
        conn.commit()


def test_demo_can_send_email_and_sender_is_logged(as_role, evaluated_candidate, monkeypatch, caplog):
    """ส่งได้เหมือน HR จริง — แต่ log ต้องบอกว่าใครกด (บทเรียน 2026-10-16: ตอบไม่ได้ว่าใครส่ง)."""
    sent: list[dict] = []
    monkeypatch.setattr("app.routers.hr.send_email", lambda **kw: sent.append(kw))
    caplog.set_level("INFO", logger="app.routers.hr")
    r = as_role("demo").post(
        f"/api/v1/candidates/{evaluated_candidate}/email/send",
        json={"to": "me@example.com", "subject": "เชิญสัมภาษณ์", "body": "ขอเชิญ"},
    )
    assert r.status_code == 200
    assert sent and sent[0]["to"] == "me@example.com"
    assert "demo-test ส่งอีเมลถึง me@example.com" in caplog.text


def test_disabled_settings_still_readable_by_demo(as_role):
    assert as_role("demo").get("/api/v1/settings/screening-photos").status_code == 200


# ── role จริงจาก DB (ไม่แทน get_current_role) ──

@pytest.fixture
def db_user():
    names: list[str] = []

    def _make(role: str | None) -> str:
        name = f"roletest-{uuid.uuid4().hex[:8]}"
        with get_conn() as conn:
            if role is None:
                conn.execute("INSERT INTO users (username, password_hash) VALUES (%s, 'x')", (name,))
            else:
                conn.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (%s, 'x', %s)", (name, role)
                )
            conn.commit()
        names.append(name)
        return name

    yield _make
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE username = ANY(%s)", (names,))
        conn.commit()


def _real_client(username: str) -> TestClient:
    app.dependency_overrides.pop(get_current_role, None)  # อ่าน role จาก DB จริง
    app.dependency_overrides[get_current_user] = lambda: username
    return TestClient(app)


def test_me_reports_role_from_db(db_user):
    c = _real_client(db_user("demo"))
    assert c.get("/api/v1/auth/me").json()["role"] == "demo"
    assert c.delete(f"/api/v1/jobs/{RID}").status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


def test_new_row_without_role_is_least_privilege(db_user):
    """ลืมระบุ role ตอนสร้างบัญชี → ได้ demo ไม่ใช่ admin."""
    c = _real_client(db_user(None))
    assert c.get("/api/v1/auth/me").json()["role"] == "demo"
    app.dependency_overrides.pop(get_current_user, None)


def test_role_change_applies_immediately(db_user):
    name = db_user("demo")
    c = _real_client(name)
    assert c.delete(f"/api/v1/jobs/{RID}").status_code == 403
    with get_conn() as conn:
        conn.execute("UPDATE users SET role = 'admin' WHERE username = %s", (name,))
        conn.commit()
    assert c.delete(f"/api/v1/jobs/{RID}").status_code == 404
    app.dependency_overrides.pop(get_current_user, None)


def test_bad_role_rejected_by_db(db_user):
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        db_user("superuser")


# ── สคริปต์ manage_users (ส่วนที่เป็นฟังก์ชันบริสุทธิ์) ──

def test_check_username():
    assert check_username("teacher") is None
    assert check_username("a.b_c-1") is None
    assert check_username("ab")  # สั้นไป
    assert check_username("อาจารย์")  # ภาษาไทย — พิมพ์ตอนล็อกอินบนมือถือยาก
    assert check_username("x y")


def test_check_password():
    assert check_password("longenough1", "longenough1") is None
    assert check_password("short", "short")
    assert check_password("longenough1", "longenough2")


def test_last_admin_is_protected():
    assert leaves_no_admin(["boss"], "boss", None)  # ลบคนสุดท้าย
    assert leaves_no_admin(["boss"], "boss", "demo")  # ลดสิทธิ์คนสุดท้าย
    assert not leaves_no_admin(["boss", "b2"], "boss", None)
    assert not leaves_no_admin(["boss"], "teacher", None)  # ลบ demo ได้เสมอ
    assert not leaves_no_admin(["boss"], "boss", "admin")
