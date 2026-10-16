"""ประวัติการใช้งาน (audit_log) — ใครทำอะไร เมื่อไร สำเร็จไหม.

ตัวจดกลาง (AuditMiddleware) อ่าน Bearer token เอง จึงใช้ token จริงของผู้ใช้จริงในตาราง users
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app import audit
from app.audit import ACTIONS, SKIP, WRITE_METHODS, _api_routes, outcome_of, pick_detail, target_of
from app.auth import create_token, get_current_role, hash_password
from app.database import get_conn
from app.main import app

RID = str(uuid.uuid4())


# ── ครบทุก route (กันลืม) ──

def _write_routes() -> set[tuple[str, str]]:
    return {(m, r.path) for r in _api_routes(app.routes) for m in r.methods if m in WRITE_METHODS}


def test_every_write_route_is_named_or_skipped():
    """มี endpoint ใหม่ที่เปลี่ยนข้อมูลแต่ไม่ได้ตั้งชื่อภาษาคน → พังที่นี่."""
    routes = _write_routes()
    assert len(routes) >= 25, "หา route ไม่ครบ — วิธีไล่ route เพี้ยน"
    missing = routes - set(ACTIONS) - SKIP
    assert not missing, f"ยังไม่มีชื่อใน audit.ACTIONS: {missing}"


def test_no_stale_names():
    assert set(ACTIONS) | SKIP <= _write_routes(), "มีชื่อของ route ที่ไม่มีอยู่แล้ว"


# ── ฟังก์ชันบริสุทธิ์ ──

def test_pick_detail_never_keeps_personal_data():
    body = {
        "decision": "approved", "notes": "ลับมาก", "salary": 45000, "note": "x", "body": "เนื้อความ",
        "subject": "หัวข้อ", "decline_reason": "เหตุผล", "to": "a@example.com", "position": "Dev",
        "candidate_ids": ["a", "b", "c"],
    }
    assert pick_detail(body) == {"decision": "approved", "to": "a@example.com", "count": 3}
    assert pick_detail({"name": "x" * 300}) == {}  # ยาวผิดปกติ ไม่เก็บ
    assert pick_detail(["not", "a", "dict"]) == {}


def test_outcome_and_target():
    assert outcome_of(200) == "ok" and outcome_of(202) == "ok"
    assert outcome_of(403) == "denied"
    assert outcome_of(404) == "error" and outcome_of(409) == "error"
    assert outcome_of(401) is None
    assert target_of({"candidate_id": RID, "job_id": RID}) == ("candidate", RID)
    assert target_of({"job_id": RID}) == ("job", RID)
    assert target_of({"job_id": "analyze"}) == (None, None)


# ── จดจริงผ่าน HTTP ──

@pytest.fixture
def user():
    names: list[str] = []

    def _make(role: str = "demo", password: str | None = None) -> str:
        name = f"audit-{uuid.uuid4().hex[:8]}"
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                (name, hash_password(password) if password else "x", role),
            )
            conn.commit()
        names.append(name)
        return name

    yield _make
    with get_conn() as conn:
        conn.execute("DELETE FROM audit_log WHERE username = ANY(%s)", (names,))
        conn.execute("DELETE FROM users WHERE username = ANY(%s)", (names,))
        conn.commit()
    app.dependency_overrides.pop(get_current_role, None)


def _client(username: str) -> TestClient:
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {create_token(username)}"
    return c


def _rows(username: str) -> list[dict]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT action, target_type, target_id::text AS target_id, detail, outcome, status_code "
            "FROM audit_log WHERE username = %s ORDER BY id",
            (username,),
        ).fetchall()


def test_write_is_recorded_with_target_and_detail(user):
    name = user("admin")
    r = _client(name).patch(f"/api/v1/jobs/{RID}", json={"status": "closed"})
    assert r.status_code == 404
    [row] = _rows(name)
    assert row["action"] == "PATCH /api/v1/jobs/{job_id}"
    assert (row["target_type"], row["target_id"]) == ("job", RID)
    assert row["detail"] == {"status": "closed"}
    assert (row["outcome"], row["status_code"]) == ("error", 404)


def test_denied_is_recorded(user):
    name = user("demo")
    app.dependency_overrides[get_current_role] = lambda: "demo"
    assert _client(name).delete(f"/api/v1/jobs/{RID}").status_code == 403
    [row] = _rows(name)
    assert row["outcome"] == "denied" and row["action"] == "DELETE /api/v1/jobs/{job_id}"


def test_salary_never_reaches_the_table(user):
    name = user("admin")
    _client(name).put(
        f"/api/v1/candidates/{RID}/offer",
        json={"position": "Dev", "salary": 98765, "note": "ลับ"},
    )
    [row] = _rows(name)
    assert "98765" not in str(row["detail"]) and "ลับ" not in str(row["detail"])


def test_reads_previews_and_anonymous_are_not_recorded(user):
    name = user("admin")
    c = _client(name)
    c.get("/api/v1/jobs")
    c.post(f"/api/v1/jobs/{RID}/criteria/preview", json={})
    TestClient(app).patch(f"/api/v1/jobs/{RID}", json={"status": "closed"})  # ไม่มี token → 401
    assert _rows(name) == []


def test_recording_failure_never_breaks_the_request(user, monkeypatch):
    name = user("admin")

    def boom():
        raise RuntimeError("db ล่ม")

    monkeypatch.setattr(audit, "get_conn", boom)
    assert _client(name).patch(f"/api/v1/jobs/{RID}", json={"status": "closed"}).status_code == 404


def test_login_success_and_failure_on_real_account(user):
    name = user("demo", password="correct-horse-1")
    c = TestClient(app)
    assert c.post("/api/v1/auth/login", json={"username": name, "password": "wrong-pass-1"}).status_code == 401
    assert c.post("/api/v1/auth/login", json={"username": name, "password": "correct-horse-1"}).status_code == 200
    assert [(r["action"], r["outcome"]) for r in _rows(name)] == [("login", "failed"), ("login", "ok")]


def test_login_failure_for_unknown_name_is_not_recorded():
    ghost = f"ghost-{uuid.uuid4().hex[:8]}"
    TestClient(app).post("/api/v1/auth/login", json={"username": ghost, "password": "whatever-123"})
    assert _rows(ghost) == []


# ── หน้าประวัติ ──

def test_admin_reads_history_demo_cannot(user):
    admin = user("admin")
    _client(admin).patch(f"/api/v1/jobs/{RID}", json={"status": "closed"})
    out = _client(admin).get("/api/v1/audit", params={"username": admin}).json()
    [item] = out["items"]
    assert item["label"] == "เปลี่ยนสถานะตำแหน่ง"
    assert item["target_deleted"] is True  # ตำแหน่ง RID ไม่มีอยู่จริง → ขึ้นว่าลบแล้ว
    assert admin in out["users"]

    demo = user("demo")
    app.dependency_overrides[get_current_role] = lambda: "demo"
    assert _client(demo).get("/api/v1/audit").status_code == 403


def test_live_name_lookup_and_no_name_stored(user):
    admin = user("admin")
    with get_conn() as conn:
        job = conn.execute(
            "INSERT INTO jobs (title, raw_text) VALUES ('เทสประวัติ (ลบได้)', 'x') RETURNING id::text"
        ).fetchone()["id"]
        conn.commit()
    try:
        _client(admin).patch(f"/api/v1/jobs/{job}", json={"status": "closed"})
        [item] = _client(admin).get("/api/v1/audit", params={"username": admin}).json()["items"]
        assert item["target_label"] == "เทสประวัติ (ลบได้)" and item["job_id"] == job
        assert "เทสประวัติ" not in str(_rows(admin))  # ชื่อไม่ได้ลงตาราง
    finally:
        with get_conn() as conn:
            conn.execute("DELETE FROM jobs WHERE id = %s", (job,))
            conn.commit()


def test_rows_older_than_a_year_are_purged(user):
    name = user("admin")
    with get_conn() as conn:
        for days in (400, 300):
            conn.execute(
                "INSERT INTO audit_log (username, action, outcome, at) "
                "VALUES (%s, 'login', 'ok', timezone('utc'::text, now()) - make_interval(days => %s))",
                (name, days),
            )
        conn.commit()
    audit.purge_expired()
    assert len(_rows(name)) == 1
