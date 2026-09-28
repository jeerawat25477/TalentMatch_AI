"""HR ยืนยันว่าถ้อยคำที่ตัวตรวจอคติเตือน "จำเป็นกับงานนี้" — กติกาใน app/bias_ack.py + endpoint.

ไม่เรียก LLM เลยทั้งไฟล์
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Json

from app.auth import get_current_user
from app.bias_ack import MIN_REASON_CHARS, AckError, bias_view, validate_acks
from app.database import get_conn
from app.main import app

NOW = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)
REASON = "งานตรวจค้นตัวผู้โดยสารหญิง กฎหมายกำหนด"
CRITERIA = ["เพศหญิง", "อายุไม่เกิน 30 ปี"]
AUDIT = {
    "status": "flagged", "log": "พบถ้อยคำที่อาจมีอคติ (เพศ, อายุ)\n⚠ ...",
    "jd_criteria": CRITERIA, "biased_required_skills": [], "biased_preferred_skills": [],
    "llm_checked": True,
}


# ── validate_acks ──


def test_รับเฉพาะถ้อยคำที่อยู่ในผลตรวจจริง():
    out = validate_acks(
        [{"phrase": "เพศหญิง", "reason": REASON}, {"phrase": "แต่งขึ้นเอง", "reason": REASON}],
        CRITERIA, "hr1", NOW,
    )
    assert [a["phrase"] for a in out] == ["เพศหญิง"]


def test_ชื่อและเวลามาจากฝั่ง_server():
    [a] = validate_acks([{"phrase": "เพศหญิง", "reason": REASON}], CRITERIA, "hr1", NOW)
    assert a["by"] == "hr1" and a["at"] == NOW.isoformat()


@pytest.mark.parametrize("reason", ["", "ok", "   จำเป็น   "])
def test_เหตุผลสั้นเกินไม่รับ(reason):
    assert len(" ".join(reason.split())) < MIN_REASON_CHARS
    with pytest.raises(AckError):
        validate_acks([{"phrase": "เพศหญิง", "reason": reason}], CRITERIA, "hr1", NOW)


def test_ถ้อยคำซ้ำเก็บอันแรก():
    out = validate_acks(
        [{"phrase": "เพศหญิง", "reason": REASON}, {"phrase": "เพศหญิง", "reason": REASON + " อีก"}],
        CRITERIA, "hr1", NOW,
    )
    assert len(out) == 1 and out[0]["reason"] == REASON


def test_ข้อเดิมเหตุผลเดิมคงคนยืนยันเดิม():
    """แก้รายการอื่นต้องไม่ทำให้ดูเหมือนคนล่าสุดเป็นคนยืนยันทุกข้อ."""
    old = [{"phrase": "เพศหญิง", "reason": REASON, "by": "hr1", "at": "2026-09-01T00:00:00+00:00"}]
    out = validate_acks(
        [{"phrase": "เพศหญิง", "reason": REASON},
         {"phrase": "อายุไม่เกิน 30 ปี", "reason": "งานใช้แรงยกของหนักทุกวัน"}],
        CRITERIA, "hr2", NOW, old,
    )
    assert out[0] == old[0]
    assert out[1]["by"] == "hr2"


def test_แก้เหตุผลนับเป็นการยืนยันใหม่():
    old = [{"phrase": "เพศหญิง", "reason": REASON, "by": "hr1", "at": "2026-09-01T00:00:00+00:00"}]
    [a] = validate_acks([{"phrase": "เพศหญิง", "reason": REASON + " มาตรา 15"}], CRITERIA, "hr2", NOW, old)
    assert a["by"] == "hr2"


# ── bias_view ──


def test_ยังไม่ยืนยัน_ทุกข้อค้างเตือน():
    v = bias_view(AUDIT, [])
    assert v["status"] == "flagged" and v["pending"] == CRITERIA and v["acknowledged"] == []
    assert v["summary"] == "พบถ้อยคำที่อาจมีอคติ (เพศ, อายุ)"


def test_ยืนยันบางข้อ_ข้อที่เหลือยังเตือน():
    acks = [{"phrase": "เพศหญิง", "reason": REASON, "by": "hr1", "at": NOW.isoformat()}]
    v = bias_view(AUDIT, acks)
    assert v["status"] == "flagged" and v["pending"] == ["อายุไม่เกิน 30 ปี"]
    assert [a["phrase"] for a in v["acknowledged"]] == ["เพศหญิง"]


def test_ยืนยันครบทุกข้อ_ไม่เหลือคำเตือน():
    acks = [{"phrase": c, "reason": REASON, "by": "hr1", "at": NOW.isoformat()} for c in CRITERIA]
    v = bias_view(AUDIT, acks)
    assert v["status"] == "passed" and v["pending"] == []


def test_เกณฑ์ทักษะที่มีอคติไม่ถูกปิดด้วยการยืนยันถ้อยคำ():
    audit = {**AUDIT, "jd_criteria": [], "biased_required_skills": ["มหาวิทยาลัยชั้นนำ"]}
    assert bias_view(audit, [])["status"] == "flagged"


def test_การยืนยันของถ้อยคำที่ไม่อยู่ในผลตรวจแล้วถูกมองข้าม():
    acks = [{"phrase": "ของเก่า", "reason": REASON, "by": "hr1", "at": NOW.isoformat()}]
    assert bias_view(AUDIT, acks)["acknowledged"] == []


def test_ไม่มีผลตรวจคืน_none():
    assert bias_view(None, []) is None


# ── endpoint ──


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: "hr-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def job():
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO jobs (title, raw_text, jd_audit) VALUES (%s, %s, %s) RETURNING id",
            ("เทสยืนยันอคติ (ลบได้)", "เจ้าหน้าที่ตรวจค้น เพศหญิง อายุไม่เกิน 30 ปี", Json(AUDIT)),
        ).fetchone()
        cand = conn.execute(
            "INSERT INTO candidates (job_id, full_name) VALUES (%s, %s) RETURNING id",
            (row["id"], "ผู้สมัครเทสอคติ"),
        ).fetchone()
        conn.commit()
    yield str(row["id"]), str(cand["id"])
    with get_conn() as conn:
        conn.execute("DELETE FROM jobs WHERE id = %s", (row["id"],))
        conn.commit()


def _put(client, job_id, acks):
    return client.put(f"/api/v1/jobs/{job_id}/bias-acknowledgements", json={"acks": acks})


def test_ต้องล็อกอิน(job):
    assert _put(TestClient(app), job[0], []).status_code == 401


def test_ยืนยันแล้วหน้าตำแหน่งเห็นทันที(client, job):
    res = _put(client, job[0], [{"phrase": "เพศหญิง", "reason": REASON}])
    assert res.status_code == 200
    bias = res.json()["bias"]
    assert bias["pending"] == ["อายุไม่เกิน 30 ปี"]
    assert bias["acknowledged"][0]["by"] == "hr-test"


def test_ถอนการยืนยันด้วยการส่งรายการว่าง(client, job):
    _put(client, job[0], [{"phrase": "เพศหญิง", "reason": REASON}])
    bias = _put(client, job[0], []).json()["bias"]
    assert bias["acknowledged"] == [] and bias["pending"] == CRITERIA


def test_เหตุผลสั้นได้_422_และไม่บันทึก(client, job):
    res = _put(client, job[0], [{"phrase": "เพศหญิง", "reason": "ok"}])
    assert res.status_code == 422 and "เหตุผล" in res.json()["detail"]
    with get_conn() as conn:
        acks = conn.execute(
            "SELECT bias_acknowledgements FROM jobs WHERE id = %s", (job[0],)
        ).fetchone()["bias_acknowledgements"]
    assert acks == []


def test_ไม่พบตำแหน่ง_404(client):
    res = _put(client, "00000000-0000-0000-0000-000000000000", [])
    assert res.status_code == 404


def test_หน้าผู้สมัครอ่านผลตรวจของตำแหน่งสด(client, job):
    job_id, cid = job
    before = client.get(f"/api/v1/candidates/{cid}").json()["job_bias"]
    assert before["pending"] == CRITERIA
    _put(client, job_id, [{"phrase": c, "reason": REASON} for c in CRITERIA])
    after = client.get(f"/api/v1/candidates/{cid}").json()["job_bias"]
    assert after["status"] == "passed" and len(after["acknowledged"]) == 2


def test_ไม่ส่งของดิบซ้ำใน_jobout(client, job):
    body = _put(client, job[0], []).json()
    assert "jd_audit" not in body and "bias_acknowledgements" not in body
