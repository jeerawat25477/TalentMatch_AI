"""ความมั่นใจของผลวิเคราะห์ — คนละมิติกับ fit score.

fit score บอกว่า "เหมาะกับงานแค่ไหน" ส่วน confidence บอกว่า "ผลนี้อิงข้อมูลครบแค่ไหน"
เคสที่ต้องไม่พลาด: ผู้สมัครที่ไม่ตรงเกณฑ์สักข้อ (matched=0) ต้องไม่ถูกตัดสินว่า confidence
ต่ำเพราะ "หาหลักฐานไม่ได้" — เราอ่านเรซูเม่เขาได้ครบดี เขาแค่ไม่ตรงงาน คนละเรื่องกัน

รัน: docker compose exec backend python -m pytest tests/test_confidence.py -v
"""
import pytest

from app.agents.bands import (
    CONFIDENCE_EVIDENCE_HIGH,
    CONFIDENCE_EVIDENCE_LOW,
    CONFIDENCE_TEXT_HIGH,
    CONFIDENCE_TEXT_LOW,
    confidence_level,
)


class TestTextLength:
    """ข้อความสั้นเกินไป = ไม่ว่าอย่างอื่นจะดีแค่ไหนก็เชื่อไม่ได้."""

    def test_สั้นกว่าเกณฑ์เป็น_low_แม้หลักฐานครบ(self):
        assert confidence_level(CONFIDENCE_TEXT_LOW - 1, 10, 10) == "low"

    def test_ตรงเกณฑ์พอดีไม่ใช่_low(self):
        # ขอบล่างเป็นแบบ "ตั้งแต่...ขึ้นไปถือว่าผ่าน"
        assert confidence_level(CONFIDENCE_TEXT_LOW, 10, 10) != "low"

    def test_ยาวพอแต่ไม่ถึงเกณฑ์สูงได้แค่_medium(self):
        assert confidence_level(CONFIDENCE_TEXT_HIGH - 1, 10, 10) == "medium"

    def test_ยาวถึงเกณฑ์สูงและหลักฐานครบเป็น_high(self):
        assert confidence_level(CONFIDENCE_TEXT_HIGH, 10, 10) == "high"


class TestEvidenceCoverage:
    LONG = CONFIDENCE_TEXT_HIGH + 500

    def test_หาหลักฐานไม่ได้เลยเป็น_low(self):
        # LLM บอกว่ามีทักษะ แต่ยืนยันกับไฟล์ไม่ได้สักอัน = สัญญาณว่า parse เพี้ยน
        assert confidence_level(self.LONG, 8, 0) == "low"

    def test_ต่ำกว่าเกณฑ์ล่างเป็น_low(self):
        # 1/8 = 0.125 < CONFIDENCE_EVIDENCE_LOW
        assert CONFIDENCE_EVIDENCE_LOW > 1 / 8
        assert confidence_level(self.LONG, 8, 1) == "low"

    def test_อยู่ระหว่างสองเกณฑ์เป็น_medium(self):
        # 4/8 = 0.5 อยู่ระหว่าง LOW กับ HIGH
        assert CONFIDENCE_EVIDENCE_LOW <= 0.5 < CONFIDENCE_EVIDENCE_HIGH
        assert confidence_level(self.LONG, 8, 4) == "medium"

    def test_ถึงเกณฑ์สูงเป็น_high(self):
        assert confidence_level(self.LONG, 10, 6) == "high"
        assert CONFIDENCE_EVIDENCE_HIGH <= 0.6


class TestNoMatchedSkills:
    """matched=0 คือ "ไม่มีสัญญาณด้านหลักฐาน" ไม่ใช่ "หลักฐาน 0%"."""

    def test_ไม่ตรงเกณฑ์สักข้อแต่เรซูเม่ยาวยังเป็น_high(self):
        assert confidence_level(CONFIDENCE_TEXT_HIGH + 100, 0, 0) == "high"

    def test_ไม่ตรงเกณฑ์สักข้อและเรซูเม่สั้นเป็น_low(self):
        assert confidence_level(CONFIDENCE_TEXT_LOW - 1, 0, 0) == "low"

    def test_ไม่หารด้วยศูนย์(self):
        # เคยพลาดกันมาแล้วในโค้ดแบบนี้ — ต้องไม่โยน ZeroDivisionError
        assert confidence_level(800, 0, 0) == "medium"


class TestReturnsValidLiteral:
    @pytest.mark.parametrize(
        "args", [(0, 0, 0), (500, 3, 1), (5000, 20, 20), (100, 1, 0)]
    )
    def test_คืนค่าที่หน้าเว็บรู้จักเสมอ(self, args):
        assert confidence_level(*args) in {"high", "medium", "low"}
