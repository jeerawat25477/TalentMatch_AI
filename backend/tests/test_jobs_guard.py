"""ทดสอบการ์ดการลบตำแหน่งงานถาวร (app.routers.jobs._deletion_blocker).

รันใน container: docker compose exec backend python -m pytest tests/ -v

การลบงานจะ cascade ไปถึงผู้สมัคร/คะแนน/hr_decisions/เวกเตอร์ ฟังก์ชันนี้จึงเป็น
ด่านเดียวที่กันข้อมูลที่ลบแล้วเรียกคืนไม่ได้ — เทสต์ไว้ให้ครบทุกกิ่ง
"""
import pytest

from app.routers.candidates import _candidate_deletion_blocker
from app.routers.jobs import _deletion_blocker


class TestDeletionBlocker:
    def test_ลบได้เมื่อไม่มีอะไรกั้น(self):
        assert _deletion_blocker(sent_count=0, active_count=0) is None

    @pytest.mark.parametrize("sent", [1, 3, 20])
    def test_เคยส่งอีเมลแล้วต้องบล็อก(self, sent):
        msg = _deletion_blocker(sent_count=sent, active_count=0)
        assert msg is not None
        assert str(sent) in msg
        assert "ปิดรับสมัคร" in msg  # ต้องบอกทางออกให้ HR ด้วย

    def test_กำลังประมวลผลต้องบล็อก(self):
        msg = _deletion_blocker(sent_count=0, active_count=2)
        assert msg is not None
        assert "ประมวลผล" in msg

    def test_อีเมลชนะกำลังประมวลผล(self):
        """ทั้งคู่ติด → รายงานเหตุถาวร (อีเมล) ไม่ใช่เหตุชั่วคราว ไม่งั้น HR จะรอเก้อ."""
        msg = _deletion_blocker(sent_count=1, active_count=5)
        assert msg is not None
        assert "อีเมล" in msg
        assert "ประมวลผล" not in msg


class TestCandidateDeletionBlocker:
    """การ์ดลบผู้สมัครรายคน — ใช้กฎเดียวกับการลบตำแหน่งงาน."""

    def test_ลบได้เมื่อไม่มีอะไรกั้น(self):
        assert _candidate_deletion_blocker(email_sent=False, is_active=False) is None

    def test_เคยส่งอีเมลแล้วต้องบล็อก(self):
        msg = _candidate_deletion_blocker(email_sent=True, is_active=False)
        assert msg is not None
        assert "อีเมล" in msg

    def test_กำลังวิเคราะห์อยู่ต้องบล็อก(self):
        msg = _candidate_deletion_blocker(email_sent=False, is_active=True)
        assert msg is not None
        assert "วิเคราะห์" in msg

    def test_มีคะแนนแล้วแต่ยังไม่ส่งอีเมล_ลบได้(self):
        """เคสหลักที่ฟีเจอร์นี้มีไว้แก้: อัปผิดไฟล์แล้ววิเคราะห์เสร็จไปแล้ว."""
        assert _candidate_deletion_blocker(email_sent=False, is_active=False) is None
