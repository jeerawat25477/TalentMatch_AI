"""แปลงไฟล์ PDF เป็นข้อความ (ใช้ในขั้นอัปโหลด resume).

**ทำไมถึงเป็น pypdfium2 ไม่ใช่ pdfplumber:** pdfplumber ประกอบบรรทัดโดยเรียง glyph ตาม
"พิกัด x" ภาษาไทยวางสระบน/ล่างและวรรณยุกต์ไว้เหนือพยัญชนะ (พิกัด x ทับกัน) ลำดับที่ได้จึงสลับ
เช่น `จีรวัฒน์` กลายเป็น `จรี วฒั น์` และ `ศักดิ์` กลายเป็น `ศักดิ` — ชื่อ/การศึกษาที่ HR อ่านเพี้ยน
ทั้งที่ทักษะ (Latin) ยังถูก. pypdfium2 อ่านตามลำดับใน content stream จึงไม่มีปัญหานี้
pdfplumber ยังถูกเก็บไว้เป็นทางสำรองสำหรับ PDF ที่ pdfium แกะไม่ออก
"""
import io
import logging
import os

import pdfplumber
import pypdfium2 as pdfium

log = logging.getLogger(__name__)

# แกะแค่ N หน้าแรก — กัน decompression bomb ที่ไฟล์เล็กแต่แตกเป็นข้อความมหาศาล
# (คู่กับ MAX_UPLOAD_MB / MAX_FILES ที่จำกัดขนาดและจำนวนไฟล์ใน routers/candidates.py)
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "30"))


def _finish(parts: list[str]) -> str:
    """รวมทุกหน้า, ทำ line ending ให้เป็น \\n, และล้างอักขระที่ Postgres เก็บไม่ได้.

    - บาง PDF (ฟอนต์ฝังแบบแปลก ๆ) แกะข้อความออกมาปน NUL (0x00) — คอลัมน์ text ของ Postgres
      เก็บ NUL ไม่ได้ (DataError) ต้องล้างที่ต้นทาง ครอบคลุมทั้งตอนอัปโหลดและ reprocess
    - pdfium คืนบรรทัดแบบ CRLF ถ้าไม่ล้าง \\r มันจะติดไปทั้งใน raw_resume_text และใน prompt
    """
    text = "\n".join(parts).replace("\x00", "")
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _extract_pypdfium(data: bytes) -> str:
    """ทางหลัก — อ่านตามลำดับ content stream (ภาษาไทยไม่สลับตำแหน่ง)."""
    parts: list[str] = []
    pdf = pdfium.PdfDocument(io.BytesIO(data))
    try:
        for i in range(min(len(pdf), MAX_PDF_PAGES)):
            page = pdf[i]
            textpage = page.get_textpage()
            try:
                parts.append(textpage.get_text_range() or "")
            finally:
                # pdfium ถือ handle ของ C library ต้องปิดเอง ไม่ได้พึ่ง GC
                textpage.close()
                page.close()
    finally:
        pdf.close()
    return _finish(parts)


def _extract_pdfplumber(data: bytes) -> str:
    """ทางสำรอง — ลำดับตัวอักษรไทยเชื่อถือไม่ได้ ใช้เมื่อ pdfium แกะไม่ออกเท่านั้น."""
    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:MAX_PDF_PAGES]:
            parts.append(page.extract_text() or "")
    return _finish(parts)


def extract_text_from_pdf(data: bytes) -> str:
    """คืนข้อความรวมทุกหน้าจากไบต์ของไฟล์ PDF (เว้นบรรทัดคั่นระหว่างหน้า)."""
    try:
        text = _extract_pypdfium(data)
        if text:
            return text
        log.warning("pypdfium2 แกะข้อความไม่ได้เลย — ลอง pdfplumber ต่อ")
    except Exception as exc:  # noqa: BLE001 — PDF เสีย/เข้ารหัส ไม่ควรจบแค่ engine เดียว
        log.warning("pypdfium2 แกะ PDF ล้มเหลว (%s) — ลอง pdfplumber ต่อ", exc)
    return _extract_pdfplumber(data)
