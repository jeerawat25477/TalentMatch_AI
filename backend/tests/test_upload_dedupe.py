"""ทดสอบด่านตรวจตอนอัปโหลดเรซูเม่ — ไฟล์ซ้ำ และไฟล์ที่อ่านข้อความไม่ออก.

ไฟล์ซ้ำหนึ่งใบ = ผู้สมัครเกินมาหนึ่งแถว + กราฟรันฟรีอีกรอบ (~3 chat calls จากโควตา 20/วัน)
และเปิดช่องส่งอีเมลหาคนเดียวกันสองครั้ง — ด่านนี้จึงต้องแน่น

รันใน container: docker compose exec backend python -m pytest tests/ -v
"""
import hashlib

import pytest

from app.routers.candidates import _is_duplicate_upload, _is_unreadable_resume

A = hashlib.sha256(b"resume A").hexdigest()
B = hashlib.sha256(b"resume B").hexdigest()


class TestIsDuplicateUpload:
    def test_ไฟล์ใหม่ล้วนต้องผ่าน(self):
        assert _is_duplicate_upload(A, seen_in_batch=set(), existing_in_job=set()) is False

    def test_ซ้ำกับไฟล์ในชุดเดียวกัน(self):
        """ลากไฟล์เดิมมาวางสองครั้งในการอัปโหลดครั้งเดียว."""
        assert _is_duplicate_upload(A, seen_in_batch={A}, existing_in_job=set()) is True

    def test_ซ้ำกับที่เคยอัปโหลดไว้ก่อนหน้า(self):
        assert _is_duplicate_upload(A, seen_in_batch=set(), existing_in_job={A}) is True

    def test_ไฟล์อื่นในชุด_ไม่ทำให้ถูกมองว่าซ้ำ(self):
        """เจอ B มาก่อนไม่ได้แปลว่า A ซ้ำ — กันเคสข้ามไฟล์ที่ควรรับ."""
        assert _is_duplicate_upload(A, seen_in_batch={B}, existing_in_job={B}) is False

    def test_ตัดสินด้วยเนื้อไฟล์_ไม่ใช่ชื่อไฟล์(self):
        """เปลี่ยนชื่อไฟล์แล้วอัปใหม่ = ยังซ้ำ / แก้เนื้อแล้วอัปใหม่ = ไม่ซ้ำ."""
        same_bytes_renamed = hashlib.sha256(b"resume A").hexdigest()
        edited = hashlib.sha256("resume A (แก้แล้ว)".encode()).hexdigest()

        assert _is_duplicate_upload(same_bytes_renamed, set(), {A}) is True
        assert _is_duplicate_upload(edited, set(), {A}) is False


class TestIsUnreadableResume:
    """เรซูเม่สแกน/ถ่ายรูปไม่มีชั้นข้อความ ถ้าปล่อยผ่านจะเสียโควตา ~3 chat calls ให้ AI
    วิเคราะห์ความว่างเปล่า แล้วได้ผู้สมัครคะแนนมั่ว ๆ ปนในรายชื่อโดย HR ไม่รู้ตัว"""

    @pytest.mark.parametrize("text", ["", "   ", "\n\n\t  \n", None])
    def test_ว่างเปล่าถือว่าอ่านไม่ออก(self, text):
        assert _is_unreadable_resume(text) is True

    def test_สั้นเกินเกณฑ์ถือว่าอ่านไม่ออก(self):
        """PDF ที่หลุดมาแค่หัวกระดาษไม่กี่ตัว ใช้ประเมินอะไรไม่ได้."""
        assert _is_unreadable_resume("Resume") is True

    def test_ช่องว่างเยอะไม่ช่วยให้ผ่าน(self):
        """นับเฉพาะอักขระที่ไม่ใช่ช่องว่าง — บาง PDF คืนช่องว่างมาเป็นพรืดโดยไม่มีเนื้อจริง."""
        assert _is_unreadable_resume("a" * 20 + " " * 500) is True

    def test_เรซูเม่อังกฤษปกติต้องผ่าน(self):
        text = (
            "Suda Rakdee\nEmail: suda@example.com\n"
            "Summary: Backend developer with 3 years of experience.\n"
            "Skills: Python, FastAPI, Docker, MongoDB\n"
        )
        assert _is_unreadable_resume(text) is False

    def test_เรซูเม่ไทยปกติต้องผ่าน(self):
        """กันด่านแน่นเกินจนของดีไม่ผ่าน — ไทยไม่เว้นวรรคระหว่างคำ ยิ่งต้องนับให้ถูก."""
        text = (
            "จีรวัฒน์ ศักดิ์วงษ์\n"
            "นักศึกษาปีสุดท้าย สาขาคอมพิวเตอร์ธุรกิจ มหาวิทยาลัยมหาสารคาม\n"
            "ทักษะ: Python, FastAPI, PostgreSQL, LangGraph\n"
        )
        assert _is_unreadable_resume(text) is False
