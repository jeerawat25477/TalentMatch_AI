"""ด่านตรวจหลักฐานทักษะ — กันไม่ให้ "ข้อความที่ LLM แต่งเอง" ไปโผล่หน้า HR.

หลักฐานปลอมอันตรายกว่าไม่มีหลักฐาน เพราะ HR จะเชื่อโดยไม่กลับไปเปิดไฟล์เรซูเม่จริง
เทสชุดนี้จึงเน้นสองด้านเท่า ๆ กัน: ของจริงที่หน้าตาเพี้ยนเพราะ PDF ต้องผ่าน และ
ของที่ฟังดูสมเหตุสมผลแต่ไม่ได้อยู่ในไฟล์ต้องตก

รัน: docker compose exec backend python -m pytest tests/test_evidence.py -v
"""
import pytest

from app.agents.evidence import (
    MAX_EVIDENCE_CHARS,
    filter_evidence,
    verify_evidence,
)

# ข้อความเรซูเม่ตัวอย่าง — เว้นวรรค/ขึ้นบรรทัดแบบที่ PyMuPDF สกัดออกมาจริง
RAW = """John Doe
Senior Backend Engineer

Experience:
- Built CI/CD pipelines with Docker and GitHub Actions
- Designed PostgreSQL schemas for a 2M-row analytics table
- Led a team of 4 engineers

Skills: Python, Docker, PostgreSQL, FastAPI
"""

RAW_TH = """จีรวัฒน์ ศักดิ์วงษ์
ประสบการณ์: พัฒนาระบบหลังบ้านด้วย Python และ FastAPI มา 3 ปี
รับผิดชอบการออกแบบฐานข้อมูล PostgreSQL
"""


class TestVerifyEvidence:
    """quote ต้องมาจากไฟล์จริงเท่านั้น."""

    def test_คัดลอกมาตรงเป๊ะ(self):
        assert verify_evidence("Built CI/CD pipelines with Docker", RAW) is True

    def test_ต่างแค่ช่องว่างและขึ้นบรรทัด(self):
        # PDF ตัดบรรทัดกลางประโยคเป็นเรื่องปกติ ถ้าเทียบดิบ ๆ ของจริงจะตกเกือบหมด
        assert verify_evidence("Built  CI/CD\n  pipelines\twith Docker", RAW) is True

    def test_ต่างแค่ตัวพิมพ์เล็กใหญ่(self):
        assert verify_evidence("BUILT CI/CD PIPELINES WITH DOCKER", RAW) is True

    def test_ภาษาไทยคัดลอกมาจริง(self):
        assert verify_evidence("ออกแบบฐานข้อมูล PostgreSQL", RAW_TH) is True

    def test_พิมพ์ผิดเล็กน้อยยังผ่าน(self):
        # OCR/ฟอนต์เพี้ยนทำให้หลุดไปตัวสองตัวได้ ไม่ควรตกเพราะเรื่องนี้
        assert verify_evidence("Built CI/CD pipelnes with Docker", RAW) is True

    def test_LLM_แต่งเองต้องตก(self):
        # ฟังดูเหมือนอยู่ในเรซูเม่มาก แต่ไม่มีข้อความนี้ในไฟล์ — เคสที่เทสชุดนี้มีไว้เพื่อกัน
        assert verify_evidence("Managed Kubernetes clusters in production", RAW) is False

    def test_สรุปความแทนการคัดลอกต้องตก(self):
        assert verify_evidence("มีประสบการณ์ด้าน DevOps อย่างกว้างขวาง", RAW) is False

    @pytest.mark.parametrize("quote", ["", "   ", "\n\t "])
    def test_quote_ว่างต้องตก(self, quote):
        assert verify_evidence(quote, RAW) is False

    @pytest.mark.parametrize("raw", ["", "   ", None])
    def test_raw_ว่างต้องตก(self, raw):
        assert verify_evidence("Docker", raw) is False

    def test_ต่อเติมข้อความท้ายประโยคต้องตก(self):
        assert verify_evidence("Led a team of 4 engineers at Google", RAW) is False

    def test_ประกอบร่างจากหลายบรรทัดต้องตก(self):
        # กันไม่ให้เก็บตัวอักษรกระจายทั่วไฟล์มาปะติดปะต่อจนผ่านเกณฑ์
        assert (
            verify_evidence(
                "Built pipelines with Docker and Designed PostgreSQL schemas", RAW
            )
            is False
        )

    def test_ขอบเขตที่ยอมรับว่ายังผ่าน(self):
        """⚠️ ข้อจำกัดที่รู้ตัว: เกณฑ์ 0.8 ยอมให้คำเดียว/ตัวเลขเดียวเพี้ยนได้.

        แลกมากับการทนความเพี้ยนของ PDF จริง (ฟอนต์ ToUnicode พังทำให้ได้ "เปqน")
        ด่านนี้มีไว้กันการ "แต่งขึ้นทั้งประโยค" ไม่ได้กันการบิดความหมายทีละคำ
        ถ้าจะเข้มกว่านี้ต้องขยับ EVIDENCE_MIN_RATIO แล้ววัดกับเรซูเม่จริงใหม่
        """
        assert verify_evidence("Led a team of 40 engineers", RAW) is True

    def test_quote_ยาวเกินเพดานต้องตก(self):
        # ยกมาทั้งย่อหน้า = ไม่ใช่ "ประโยคอ้างอิง" แม้จะอยู่ในไฟล์จริงก็ตาม
        long_quote = "x" * (MAX_EVIDENCE_CHARS + 1)
        assert verify_evidence(long_quote, RAW + long_quote) is False


class TestFilterEvidence:
    """คัดเฉพาะที่เชื่อถือได้ ที่เหลือทิ้ง ไม่ปล่อยเข้า state/DB."""

    SKILLS = ["Python", "Docker", "PostgreSQL"]

    def test_เก็บเฉพาะอันที่ยืนยันได้(self):
        got = filter_evidence(
            {
                "Docker": "Built CI/CD pipelines with Docker",
                "PostgreSQL": "Managed Oracle RAC clusters",  # แต่งเอง
            },
            self.SKILLS,
            RAW,
        )
        assert got == {"Docker": "Built CI/CD pipelines with Docker"}

    def test_ทักษะที่ไม่ได้อยู่ในรายการต้องถูกทิ้ง(self):
        # LLM มโนชื่อทักษะเพิ่มนอกเหนือจาก skills ที่ตัวเองคืนมา
        got = filter_evidence(
            {"Kubernetes": "Led a team of 4 engineers"}, self.SKILLS, RAW
        )
        assert got == {}

    def test_คีย์ตัวพิมพ์ไม่ตรงยังจับคู่ได้และคืนการสะกดต้นฉบับ(self):
        got = filter_evidence(
            {" docker ": "Built CI/CD pipelines with Docker"}, self.SKILLS, RAW
        )
        assert got == {"Docker": "Built CI/CD pipelines with Docker"}

    @pytest.mark.parametrize("evidence", [{}, None, "ไม่ใช่ dict"])
    def test_อินพุตพังต้องได้ผลว่าง(self, evidence):
        assert filter_evidence(evidence, self.SKILLS, RAW) == {}

    def test_ค่าที่ไม่ใช่สตริงต้องถูกทิ้ง(self):
        assert filter_evidence({"Docker": None}, self.SKILLS, RAW) == {}
        assert filter_evidence({"Docker": 123}, self.SKILLS, RAW) == {}
