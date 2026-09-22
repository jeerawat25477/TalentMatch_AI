"""ทดสอบตัวสกัดข้อความจาก PDF (PyMuPDF เป็นหลัก, pdfplumber เป็นทางสำรอง).

ข้อจำกัดที่ต้องรู้: เทสต์ชุดนี้ **ไม่ได้** ครอบบั๊กภาษาไทยที่เป็นเหตุผลของการสลับ engine
เพราะ PDF ที่ reportlab สร้าง (ตัวเดียวที่สร้างซ้ำได้ใน CI) วางข้อความทั้งบรรทัดเป็นก้อนเดียว
บั๊กจึงไม่เกิด — ลองแล้ว pdfplumber แกะไฟล์แบบนั้นถูกต้อง บั๊กเกิดกับ PDF จริงที่วาง glyph ทีละตัว
ซึ่งพิสูจน์ด้วยไฟล์จริงเท่านั้น (ทำไปแล้วกับเรซูเม่ไทย 2 ใบ ดู memory-bank/02_progress.md)
"""
import io

import pymupdf
import pytest

from app.utils import pdf_extractor
from app.utils.pdf_extractor import (
    _extract_pdfplumber,
    _extract_pymupdf,
    extract_text_from_pdf,
)

SAMPLES = ["strong_somchai", "mid_suda", "weak_anan"]


def _sample(name: str) -> bytes:
    with open(f"sample_data/{name}.pdf", "rb") as fh:
        return fh.read()


@pytest.mark.parametrize("name", SAMPLES)
def test_both_engines_read_the_sample_resumes(name):
    """สอง engine ต้องอ่านเรซูเม่ตัวอย่าง (อังกฤษ) ได้เนื้อหาเดียวกัน — ต่างได้แค่การเว้นวรรค."""
    data = _sample(name)
    mupdf_text = _extract_pymupdf(data)
    plumber_text = _extract_pdfplumber(data)

    assert "Email:" in mupdf_text
    assert "Skills:" in mupdf_text
    # เทียบแบบไม่สนช่องว่าง — สอง engine ตัดบรรทัด/เว้นวรรคต่างกันเล็กน้อย
    assert "".join(mupdf_text.split()) == "".join(plumber_text.split())


def test_no_carriage_returns_or_nul_survive():
    """บาง engine คืน CRLF และบาง PDF มี NUL ปน — ทั้งคู่ต้องไม่หลุดไปถึง Postgres/prompt."""
    text = extract_text_from_pdf(_sample("mid_suda"))
    assert "\r" not in text
    assert "\x00" not in text
    assert text == text.strip()


def test_page_cap_is_respected(monkeypatch):
    """MAX_PDF_PAGES กัน decompression bomb — แกะเกินโควตาหน้าไม่ได้."""
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page(width=200, height=200)
    many_pages = doc.tobytes()

    # หน้าเปล่าไม่มีข้อความให้นับ จึงดักที่ _finish เพื่อวัด "จำนวนหน้าที่ถูกวนจริง" แทน
    seen: dict[str, int] = {}

    def spy(parts: list[str]) -> str:
        seen["pages"] = len(parts)
        return ""

    monkeypatch.setattr(pdf_extractor, "MAX_PDF_PAGES", 1)
    monkeypatch.setattr(pdf_extractor, "_finish", spy)
    _extract_pymupdf(many_pages)

    assert seen["pages"] == 1  # ไฟล์มี 3 หน้า แต่ต้องแตะแค่หน้าเดียว


def test_falls_back_to_pdfplumber_when_primary_fails(monkeypatch):
    """engine หลักล้ม/แกะไม่ออก ต้องไม่จบแค่นั้น — ยังต้องได้ข้อความจากทางสำรอง."""
    def boom(_data: bytes) -> str:
        raise RuntimeError("engine หลักพัง")

    monkeypatch.setattr(pdf_extractor, "_extract_pymupdf", boom)
    assert "Suda Rakdee" in extract_text_from_pdf(_sample("mid_suda"))


def test_falls_back_when_primary_returns_empty(monkeypatch):
    """PDF บางแบบ engine หลักคืนว่างโดยไม่ error — ต้องลองทางสำรองด้วย ไม่ใช่คืนว่างเลย."""
    monkeypatch.setattr(pdf_extractor, "_extract_pymupdf", lambda _data: "")
    assert "Suda Rakdee" in extract_text_from_pdf(_sample("mid_suda"))


# ---------- รหัสพิเศษของฟอนต์ไทย (U+F700–F71A) ----------
# ของจริงจากเรซูเม่ที่ใช้ฟอนต์ FCMinimal — PyMuPDF คืนรหัสเหล่านี้แทนวรรณยุกต์/สระ
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ปรียานนท กรุตนิด", "ปรียานนท์ กรุตนิด"),
        ("คอมพิวเตอรธุรกิจ", "คอมพิวเตอร์ธุรกิจ"),
        ("ผูอื่นไดดี", "ผู้อื่นได้ดี"),
        ("ประวัติสวนตัว", "ประวัติส่วนตัว"),
        ("ตุกตา", "ตุ๊กตา"),
        ("อายุ 20 ป", "อายุ 20 ปี"),
        ("ทำงานเปนทีม", "ทำงานเป็นทีม"),
        ("แกไขปญหา", "แก้ไขปัญหา"),
    ],
)
def test_แปลงรหัสพิเศษของฟอนต์ไทยเป็นตัวปกติ(raw, expected):
    assert pdf_extractor.normalize_thai_pua(raw) == expected


def test_ตารางครบทุกรหัสและแปลงเป็นตัวไทยเสมอ():
    assert set(pdf_extractor.THAI_PUA_MAP) == set(range(0xF700, 0xF71B))
    assert all("฀" <= v <= "๿" for v in pdf_extractor.THAI_PUA_MAP.values())


def test_ข้อความปกติไม่เปลี่ยน():
    text = "จีรวัฒน์ ศักดิ์วงษ์ Python, FastAPI • emoji \U0001F600 "
    assert pdf_extractor.normalize_thai_pua(text) == text


def test_ทั้งสอง_engine_ผ่านการแปลงรหัสพิเศษ():
    """แปลงใน _finish ที่สอง engine ใช้ร่วมกัน — ทางสำรองจึงไม่หลุด."""
    assert pdf_extractor._finish(["คอมพิวเตอร", "ผู"]) == "คอมพิวเตอร์\nผู้"
