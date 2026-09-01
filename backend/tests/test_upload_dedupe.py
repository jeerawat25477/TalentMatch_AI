"""ทดสอบการกันอัปโหลดไฟล์เดิมซ้ำ (app.routers.candidates._is_duplicate_upload).

ไฟล์ซ้ำหนึ่งใบ = ผู้สมัครเกินมาหนึ่งแถว + กราฟรันฟรีอีกรอบ (~3 chat calls จากโควตา 20/วัน)
และเปิดช่องส่งอีเมลหาคนเดียวกันสองครั้ง — ด่านนี้จึงต้องแน่น

รันใน container: docker compose exec backend python -m pytest tests/ -v
"""
import hashlib

from app.routers.candidates import _is_duplicate_upload

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
