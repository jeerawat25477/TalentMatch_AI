"""ทดสอบตัวสกัดข้อความจาก PDF (pypdfium2 เป็นหลัก, pdfplumber เป็นทางสำรอง).

ข้อจำกัดที่ต้องรู้: เทสต์ชุดนี้ **ไม่ได้** ครอบบั๊กภาษาไทยที่เป็นเหตุผลของการสลับ engine
เพราะ PDF ที่ reportlab สร้าง (ตัวเดียวที่สร้างซ้ำได้ใน CI) วางข้อความทั้งบรรทัดเป็นก้อนเดียว
บั๊กจึงไม่เกิด — ลองแล้ว pdfplumber แกะไฟล์แบบนั้นถูกต้อง ดูรายละเอียดใน memory-bank/02_progress.md
บั๊กเกิดกับ PDF จริงที่วาง glyph ทีละตัว ซึ่งพิสูจน์ด้วยไฟล์จริงเท่านั้น
"""
import io

import pypdfium2 as pdfium
import pytest

from app.utils import pdf_extractor
from app.utils.pdf_extractor import (
    _extract_pdfplumber,
    _extract_pypdfium,
    extract_text_from_pdf,
)

SAMPLES = ["strong_somchai", "mid_suda", "weak_anan"]


def _sample(name: str) -> bytes:
    with open(f"sample_data/{name}.pdf", "rb") as fh:
        return fh.read()


@pytest.mark.parametrize("name", SAMPLES)
def test_both_engines_read_the_sample_resumes(name):
    """สอง engine ต้องอ่านเรซูเม่ตัวอย่างได้เนื้อหาเดียวกัน (ต่างได้แค่การเว้นวรรค/ตัดบรรทัด)."""
    data = _sample(name)
    pdfium_text = _extract_pypdfium(data)
    plumber_text = _extract_pdfplumber(data)

    assert "Email:" in pdfium_text
    assert "Skills:" in pdfium_text
    # เทียบแบบไม่สนช่องว่าง — pdfium เก็บช่องว่างนำหน้าบรรทัดย่อยไว้ ส่วน pdfplumber ตัดทิ้ง
    assert "".join(pdfium_text.split()) == "".join(plumber_text.split())


def test_no_carriage_returns_or_nul_survive():
    """pdfium คืน CRLF และบาง PDF มี NUL ปน — ทั้งคู่ต้องไม่หลุดไปถึง Postgres/prompt."""
    text = extract_text_from_pdf(_sample("mid_suda"))
    assert "\r" not in text
    assert "\x00" not in text
    assert text == text.strip()


def test_page_cap_is_respected(monkeypatch):
    """MAX_PDF_PAGES กัน decompression bomb — แกะเกินโควตาหน้าไม่ได้."""
    pdf = pdfium.PdfDocument.new()
    for _ in range(3):
        pdf.new_page(200, 200)
    buf = io.BytesIO()
    pdf.save(buf)
    many_pages = buf.getvalue()

    # หน้าเปล่าไม่มีข้อความให้นับ จึงดักที่ _finish เพื่อวัด "จำนวนหน้าที่ถูกวนจริง" แทน
    seen: dict[str, int] = {}

    def spy(parts: list[str]) -> str:
        seen["pages"] = len(parts)
        return ""

    monkeypatch.setattr(pdf_extractor, "MAX_PDF_PAGES", 1)
    monkeypatch.setattr(pdf_extractor, "_finish", spy)
    _extract_pypdfium(many_pages)

    assert seen["pages"] == 1  # ไฟล์มี 3 หน้า แต่ต้องแตะแค่หน้าเดียว


def test_falls_back_to_pdfplumber_when_pdfium_fails(monkeypatch):
    """pdfium ล้ม/แกะไม่ออก ต้องไม่จบแค่นั้น — ยังต้องได้ข้อความจากทางสำรอง."""
    def boom(_data: bytes) -> str:
        raise RuntimeError("pdfium พัง")

    monkeypatch.setattr(pdf_extractor, "_extract_pypdfium", boom)
    assert "Suda Rakdee" in extract_text_from_pdf(_sample("mid_suda"))


def test_falls_back_when_pdfium_returns_empty(monkeypatch):
    """PDF บางแบบ pdfium คืนว่างโดยไม่ error — ต้องลองทางสำรองด้วย ไม่ใช่คืนว่างเลย."""
    monkeypatch.setattr(pdf_extractor, "_extract_pypdfium", lambda _data: "")
    assert "Suda Rakdee" in extract_text_from_pdf(_sample("mid_suda"))
