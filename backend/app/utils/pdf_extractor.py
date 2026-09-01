"""แปลงไฟล์ PDF เป็นข้อความ (ใช้ในขั้นอัปโหลด resume).

**ทำไมถึงเป็น PyMuPDF:** ภาษาไทยวางสระบน/ล่างและวรรณยุกต์ไว้เหนือพยัญชนะ เครื่องมือออกแบบ
(Canva ฯลฯ) มักเขียน glyph พวกนี้ลง content stream *หลัง* พยัญชนะตัวถัดไป ตัวสกัดที่เรียงตาม
พิกัด x (pdfplumber) หรือเรียงตามลำดับ stream ตรง ๆ (pypdfium2) จึงได้ลำดับผิดทั้งคู่
วัดกับเรซูเม่ไทยจริง 2 ใบแล้ว:
    pdfplumber : `จรี วฒั น์ ศักดิ วงษ์`, `มหาวทิ ยาลัย`, `รบั ผดิ ชอบ`  — พังทุกคำ
    pypdfium2  : หั่นเป็นตัวอักษรเดี่ยว 300+ บรรทัด                  — แย่กว่าเดิม
    PyMuPDF    : `จีรวัฒน์`, `มหาวิทยาลัยมหาสารคาม`, `รับผิดชอบ`      — ถูกต้อง
PyMuPDF จัดลำดับ Thai combining marks ให้เอง จึงเป็นตัวเดียวที่ใช้ได้

⚠ **License: PyMuPDF เป็น AGPL-3.0** — ถ้าจะเปิดระบบนี้ให้คนนอกใช้ผ่านเครือข่าย ต้องเปิดซอร์ส
ทั้งระบบด้วย (ผู้ใช้รับทราบและเลือกทางนี้แล้ว) `pdfplumber` (MIT) ยังอยู่เป็นทางสำรอง

**ข้อจำกัดที่ยังเหลือ:** เรซูเม่บางใบฝังฟอนต์ที่ตาราง ToUnicode เสีย วรรณยุกต์บางตัวจึงออกมาเป็น
อักษรละติน (`เปqน`, `แก้ปaญหา`) — เป็นความเสียของไฟล์ ไม่ใช่ของ engine แก้ได้ด้วยตารางแมป
เฉพาะฟอนต์ ซึ่งยังไม่ทำเพราะจะพังกับ PDF ที่ใช้ฟอนต์อื่น
"""
import io
import logging
import os

import pdfplumber
import pymupdf

log = logging.getLogger(__name__)

# แกะแค่ N หน้าแรก — กัน decompression bomb ที่ไฟล์เล็กแต่แตกเป็นข้อความมหาศาล
# (คู่กับ MAX_UPLOAD_MB / MAX_FILES ที่จำกัดขนาดและจำนวนไฟล์ใน routers/candidates.py)
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "30"))


def _finish(parts: list[str]) -> str:
    """รวมทุกหน้า, ทำ line ending ให้เป็น \\n, และล้างอักขระที่ Postgres เก็บไม่ได้.

    - บาง PDF (ฟอนต์ฝังแบบแปลก ๆ) แกะข้อความออกมาปน NUL (0x00) — คอลัมน์ text ของ Postgres
      เก็บ NUL ไม่ได้ (DataError) ต้องล้างที่ต้นทาง ครอบคลุมทั้งตอนอัปโหลดและ reprocess
    - บาง engine คืนบรรทัดแบบ CRLF ถ้าไม่ล้าง \\r มันจะติดไปทั้งใน raw_resume_text และใน prompt
    """
    text = "\n".join(parts).replace("\x00", "")
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _extract_pymupdf(data: bytes) -> str:
    """ทางหลัก — จัดลำดับสระ/วรรณยุกต์ไทยได้ถูกต้อง."""
    parts: list[str] = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            if i >= MAX_PDF_PAGES:
                break
            parts.append(page.get_text("text") or "")
    return _finish(parts)


def _extract_pdfplumber(data: bytes) -> str:
    """ทางสำรอง — ลำดับตัวอักษรไทยเชื่อถือไม่ได้ ใช้เมื่อ PyMuPDF แกะไม่ออกเท่านั้น."""
    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:MAX_PDF_PAGES]:
            parts.append(page.extract_text() or "")
    return _finish(parts)


def extract_text_from_pdf(data: bytes) -> str:
    """คืนข้อความรวมทุกหน้าจากไบต์ของไฟล์ PDF (เว้นบรรทัดคั่นระหว่างหน้า)."""
    try:
        text = _extract_pymupdf(data)
        if text:
            return text
        log.warning("PyMuPDF แกะข้อความไม่ได้เลย — ลอง pdfplumber ต่อ")
    except Exception as exc:  # noqa: BLE001 — PDF เสีย/เข้ารหัส ไม่ควรจบแค่ engine เดียว
        log.warning("PyMuPDF แกะ PDF ล้มเหลว (%s) — ลอง pdfplumber ต่อ", exc)
    return _extract_pdfplumber(data)
