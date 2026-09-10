"""ทดสอบกฎ "ผู้สมัครค้าง" (app.routers.candidates._is_stalled).

รันใน container: docker compose exec backend python -m pytest tests/ -v

กฎนี้เป็นตัวตัดสินว่า UI จะบอก HR ว่า "กำลังวิเคราะห์…" (ให้รอ) หรือ "ค้าง" (ให้กดใหม่)
ถ้าผิดฝั่งไหน HR จะนั่งรอสิ่งที่ไม่มีวันมา หรือกดซ้ำทั้งที่ระบบกำลังทำงานอยู่ (เปลืองโควตา)
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.routers.candidates import _is_stalled

CID = "11111111-1111-1111-1111-111111111111"
NONE_ACTIVE: frozenset[str] = frozenset()


def _ago(seconds: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


def test_มีผลวิเคราะห์แล้วไม่ถือว่าค้าง():
    assert _is_stalled(CID, True, _ago(99999), NONE_ACTIVE) is False


def test_กำลังรันอยู่ไม่ถือว่าค้าง():
    """รวมถึงคนที่รอคิว gate — _run_graph_for_job จองทั้ง batch ตั้งแต่ต้น."""
    assert _is_stalled(CID, False, _ago(99999), frozenset({CID})) is False


def test_เพิ่งอัปโหลดยังไม่ถือว่าค้าง():
    """ช่วงผ่อนผันกันเคสแถวถูก INSERT แล้วแต่ background task ยังไม่ทันจอง."""
    assert _is_stalled(CID, False, _ago(5), NONE_ACTIVE) is False


def test_ไม่มีผลและไม่มีใครรันและเก่าแล้ว_คือค้าง():
    assert _is_stalled(CID, False, _ago(60 * 60 * 24), NONE_ACTIVE) is True


def test_เทียบ_candidate_id_แบบ_UUID_ได้():
    """DB คืน id เป็น UUID object ส่วนทะเบียนเก็บเป็น str — ต้องแปลงก่อนเทียบ."""
    from uuid import UUID

    assert _is_stalled(UUID(CID), False, _ago(99999), frozenset({CID})) is False


# ---------- ตั้งแต่มีคิวใน DB: "รอคิว" ต้องไม่ถูกตีเป็น "ค้าง" ----------
# ก่อนมีคิว ทุกคนที่ไม่มีผลวิเคราะห์เกิน 90 วิ = ค้างแน่นอน เพราะไม่มีอะไรจะมาทำต่อ
# ตอนนี้ worker ทยอยรันทีละคนตามโควตา คนที่ 10 ของ batch อาจรอเป็นชั่วโมงโดยที่
# ระบบยังดูแลอยู่ — ถ้าตีเป็นค้าง HR จะกด "วิเคราะห์ใหม่" ซ้ำแล้วเสียโควตาฟรี ๆ


@pytest.mark.parametrize("queue_status", ["queued", "running", "deferred_quota"])
def test_อยู่ในคิวไม่ถือว่าค้างไม่ว่านานแค่ไหน(queue_status):
    assert _is_stalled(CID, False, _ago(99999), NONE_ACTIVE, queue_status) is False


@pytest.mark.parametrize("queue_status", [None, "done", "failed"])
def test_ไม่มีงานค้างในคิวแล้วยังตัดสินเหมือนเดิม(queue_status):
    """done/failed = คิวจบหน้าที่แล้ว ถ้ายังไม่มีผลวิเคราะห์ก็คือค้างจริง."""
    assert _is_stalled(CID, False, _ago(99999), NONE_ACTIVE, queue_status) is True
