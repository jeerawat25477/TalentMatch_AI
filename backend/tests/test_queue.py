"""กฎการตัดสินใจของคิวงาน (app.job_queue) — ฟังก์ชันบริสุทธิ์ล้วน ไม่ต้องมี DB.

รัน: docker compose exec backend python -m pytest tests/test_queue.py -v

กฎพวกนี้เป็นตัวชี้ขาดว่างานที่ล้มจะ "ลองใหม่ / พักไว้ / เลิก" ผิดฝั่งไหนก็เจ็บคนละแบบ:
  - ตี quota เป็น temporary → งานกิน attempts จนกลายเป็น failed ทั้งที่พรุ่งนี้รันได้
  - ตี permanent เป็น temporary → ยิงซ้ำเปลืองโควตาโดยไม่มีทางสำเร็จ
"""
import pytest

from app.job_queue import (
    COST_BY_KIND,
    MAX_QUEUE_ATTEMPTS,
    classify_failure,
    estimate_cost,
    next_state,
)
from app.llm_quota import has_room


class TestEstimateCost:
    def test_งานประเมินผู้สมัครกิน_4_call(self):
        """resume_parser 2 (โปรไฟล์ + หลักฐานทักษะ) + planner + drafter.

        วัดจริง 2026-09-10 ได้ 5 (รวม bias_auditor) · 2026-09-28 ตัวตรวจอคติย้ายไปทำครั้งเดียว
        ตอนสร้างตำแหน่ง (jobs.jd_audit) โหนดอ่านอย่างเดียว จึงเหลือ 4
        """
        assert estimate_cost("process") == 4
        assert estimate_cost("reprocess") == 4

    def test_งานตัดสินกิน_2_call(self):
        """interview_planner + email_drafter เท่านั้น — กราฟ resume จากจุด interrupt."""
        assert estimate_cost("resume_after_decision") == 2

    def test_ชนิดที่ไม่รู้จักคิดแพงสุดไว้ก่อน(self):
        assert estimate_cost("อะไรก็ไม่รู้") == max(COST_BY_KIND.values())


class TestHasRoom:
    def test_เหลือพอดีเป๊ะถือว่าพอ(self):
        assert has_room(used=17, cost=3, quota=20) is True

    def test_เกินไปหนึ่งถือว่าไม่พอ(self):
        assert has_room(used=18, cost=3, quota=20) is False

    def test_ใช้หมดแล้วไม่พอแม้งานถูกสุด(self):
        assert has_room(used=20, cost=1, quota=20) is False

    def test_quota_เป็นศูนย์คือปิดการคุมโควตา(self):
        """ไว้ปิดฟีเจอร์ด้วย env ตอนอัปเกรดเป็นแพลนเสียเงิน โดยไม่ต้องแก้โค้ด."""
        assert has_room(used=9999, cost=3, quota=0) is True


class TestClassifyFailure:
    @pytest.mark.parametrize(
        "message",
        [
            "429 RESOURCE_EXHAUSTED: quota exceeded",
            "You exceeded your current quota",
            "429 Too Many Requests",
        ],
    )
    def test_โควตาหมดต้องแยกออกมาเป็น_quota(self, message):
        assert classify_failure(RuntimeError(message)) == "quota"

    @pytest.mark.parametrize(
        "message",
        ["503 Service Unavailable", "deadline exceeded", "500 internal error"],
    )
    def test_ล้มชั่วคราวต้องเป็น_temporary(self, message):
        assert classify_failure(RuntimeError(message)) == "temporary"

    @pytest.mark.parametrize(
        "message",
        ["404 NOT_FOUND: model retired", "PERMISSION_DENIED: bad key", "ไม่พบผู้สมัคร"],
    )
    def test_ล้มถาวรต้องเป็น_permanent(self, message):
        assert classify_failure(RuntimeError(message)) == "permanent"


class TestNextState:
    def test_สำเร็จคือจบ_ไม่เพิ่ม_attempts(self):
        assert next_state("ok", 1) == ("done", 1)

    def test_โควตาหมดคือพักไว้_ไม่กิน_attempts(self):
        """สำคัญที่สุดในไฟล์นี้: วันนี้โควตาหมดไม่ใช่ความผิดของงานชิ้นนั้น
        ถ้านับเป็น attempt งานจะหมดสิทธิ์ลองใหม่ทั้งที่ยังไม่เคยได้รันจริงสักครั้ง."""
        for attempts in range(MAX_QUEUE_ATTEMPTS + 5):
            assert next_state("quota", attempts) == ("deferred_quota", attempts)

    def test_ล้มชั่วคราวกลับเข้าคิวและนับเพิ่ม(self):
        assert next_state("temporary", 0) == ("queued", 1)

    def test_ล้มชั่วคราวครบเพดานแล้วเลิก(self):
        assert next_state("temporary", MAX_QUEUE_ATTEMPTS - 1)[0] == "failed"

    def test_ล้มถาวรเลิกทันทีไม่ว่านับไปเท่าไร(self):
        assert next_state("permanent", 0)[0] == "failed"
