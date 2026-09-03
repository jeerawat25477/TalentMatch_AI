"""ตัวจำกัดอัตราการเรียก — คุมโควตา LLM ไม่ให้หมดโดยไม่ตั้งใจ.

รับ bucket กับ now เป็นพารามิเตอร์ จึงทดสอบได้ตรง ๆ ไม่ต้อง mock เวลา
(ต่างจากตัวของ login ใน auth.py ที่เรียก time.time() อยู่ข้างใน)

รัน: docker compose exec backend python -m pytest tests/test_rate_limit.py -v
"""
from app.rate_limit import hit_and_check, retry_after_sec

LIMIT = 3
WINDOW = 60.0


def call(bucket, key="u1", now=1000.0):
    return hit_and_check(bucket, key, now, LIMIT, WINDOW)


class TestHitAndCheck:
    def test_ใต้เพดานผ่านหมด(self):
        b: dict = {}
        assert [call(b, now=1000.0 + i) for i in range(LIMIT)] == [True] * LIMIT

    def test_ครั้งที่เกินเพดานถูกปฏิเสธ(self):
        b: dict = {}
        for i in range(LIMIT):
            call(b, now=1000.0 + i)
        assert call(b, now=1000.0 + LIMIT) is False

    def test_นับทุกครั้งไม่ใช่เฉพาะที่สำเร็จ(self):
        """ต่างจาก login ที่นับเฉพาะครั้งที่ผิด — ตัวนี้คุมค่าใช้จ่ายจึงนับทุกการกด."""
        b: dict = {}
        for i in range(LIMIT + 2):
            call(b, now=1000.0 + i)
        assert len(b["u1"]) == LIMIT + 2

    def test_หมดหน้าต่างแล้วเริ่มนับใหม่(self):
        b: dict = {}
        for i in range(LIMIT):
            call(b, now=1000.0 + i)
        assert call(b, now=1000.0 + LIMIT) is False
        # ขยับเลยหน้าต่างไป ของเก่าต้องถูก prune ทิ้ง
        assert call(b, now=1000.0 + WINDOW + 10) is True
        assert len(b["u1"]) == 1

    def test_ขอบหน้าต่างพอดียังนับอยู่(self):
        b: dict = {}
        call(b, now=1000.0)
        # ห่างเท่ากับ window พอดี = หลุดหน้าต่างแล้ว (เงื่อนไขเป็น now - t < window)
        call(b, now=1000.0 + WINDOW)
        assert len(b["u1"]) == 1

    def test_คนละคีย์ไม่กวนกัน(self):
        b: dict = {}
        for i in range(LIMIT):
            call(b, key="u1", now=1000.0 + i)
        assert call(b, key="u1", now=1000.0 + LIMIT) is False
        # ผู้ใช้อีกคนต้องไม่โดนหางเลข
        assert call(b, key="u2", now=1000.0 + LIMIT) is True

    def test_เพดานหนึ่งครั้ง(self):
        b: dict = {}
        assert hit_and_check(b, "u1", 1000.0, 1, WINDOW) is True
        assert hit_and_check(b, "u1", 1001.0, 1, WINDOW) is False


class TestRetryAfter:
    def test_ยังไม่เคยเรียกไม่ต้องรอ(self):
        assert retry_after_sec({}, "u1", 1000.0, WINDOW) == 0

    def test_บอกเวลารอจากรายการที่เก่าที่สุด(self):
        b: dict = {}
        call(b, now=1000.0)
        call(b, now=1030.0)
        # ตัวเก่าสุดอยู่ที่ 1000 หน้าต่าง 60 วิ → ที่ 1040 เหลืออีก ~20 วิ
        assert 19 <= retry_after_sec(b, "u1", 1040.0, WINDOW) <= 21

    def test_ต้องไม่คืนศูนย์ทั้งที่ยังติดเพดาน(self):
        """ถ้าคืน 0 หน้าเว็บจะบอก "ลองใหม่ใน 0 วินาที" แล้วผู้ใช้กดซ้ำโดนปฏิเสธอีก."""
        b: dict = {}
        call(b, now=1000.0)
        assert retry_after_sec(b, "u1", 1059.9, WINDOW) >= 1
