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

**รหัสพิเศษของฟอนต์ไทย (U+F700–F71A):** ฟอนต์ไทยหลายตัว (เช่น FCMinimal) วาดวรรณยุกต์/สระ
แบบขยับตำแหน่งด้วย glyph ในช่วง Private Use Area แล้ว PyMuPDF ส่งรหัสนั้นออกมาตรง ๆ แทนตัวไทย
ปกติ วัดกับเรซูเม่จริงหนึ่งใบเจอ 45 จุด 7 แบบ (`ผู` + U+F70B แทน `ผู้`, `คอมพิวเตอร` + U+F70E
แทน `คอมพิวเตอร์`) หน้าเว็บเห็นเป็นกล่อง ▯ และ AI/การค้นหาอ่านคำผิด — ตารางนี้เป็นมาตรฐาน
เดียวกันทุกฟอนต์ (ชุดที่ libthai ใช้) จึงแปลงกลับได้ตรงตัว ต่างจากกรณีฟอนต์เสียด้านล่าง

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

# รหัสพิเศษของฟอนต์ไทย → ตัวไทยปกติ (แปลงตรงตัว 1:1 — ตำแหน่งที่ขยับหายไป ความหมายเท่าเดิม)
THAI_PUA_MAP: dict[int, str] = {
    0xF700: "ฐ",  # ฐ ไม่มีเชิง
    0xF701: "ิ",  # ิ ขยับซ้าย
    0xF702: "ี",  # ี ขยับซ้าย
    0xF703: "ึ",  # ึ ขยับซ้าย
    0xF704: "ื",  # ื ขยับซ้าย
    0xF705: "่",  # ่ ต่ำ-ซ้าย
    0xF706: "้",  # ้ ต่ำ-ซ้าย
    0xF707: "๊",  # ๊ ต่ำ-ซ้าย
    0xF708: "๋",  # ๋ ต่ำ-ซ้าย
    0xF709: "์",  # ์ ต่ำ-ซ้าย
    0xF70A: "่",  # ่ ต่ำ
    0xF70B: "้",  # ้ ต่ำ
    0xF70C: "๊",  # ๊ ต่ำ
    0xF70D: "๋",  # ๋ ต่ำ
    0xF70E: "์",  # ์ ต่ำ
    0xF70F: "ญ",  # ญ ไม่มีเชิง
    0xF710: "ั",  # ั ขยับซ้าย
    0xF711: "ํ",  # ํ ขยับซ้าย
    0xF712: "็",  # ็ ขยับซ้าย
    0xF713: "่",  # ่ ขยับซ้าย
    0xF714: "้",  # ้ ขยับซ้าย
    0xF715: "๊",  # ๊ ขยับซ้าย
    0xF716: "๋",  # ๋ ขยับซ้าย
    0xF717: "์",  # ์ ขยับซ้าย
    0xF718: "ุ",  # ุ ต่ำ
    0xF719: "ู",  # ู ต่ำ
    0xF71A: "ฺ",  # ฺ ต่ำ
}


def normalize_thai_pua(text: str) -> str:
    """แปลงรหัสพิเศษของฟอนต์ไทยกลับเป็นตัวไทยปกติ (ข้อความที่ไม่มีรหัสพวกนี้ได้คืนเท่าเดิม)."""
    return text.translate(THAI_PUA_MAP)


def _finish(parts: list[str]) -> str:
    """รวมทุกหน้า, ทำ line ending ให้เป็น \\n, และล้างอักขระที่ Postgres เก็บไม่ได้.

    - บาง PDF (ฟอนต์ฝังแบบแปลก ๆ) แกะข้อความออกมาปน NUL (0x00) — คอลัมน์ text ของ Postgres
      เก็บ NUL ไม่ได้ (DataError) ต้องล้างที่ต้นทาง ครอบคลุมทั้งตอนอัปโหลดและ reprocess
    - บาง engine คืนบรรทัดแบบ CRLF ถ้าไม่ล้าง \\r มันจะติดไปทั้งใน raw_resume_text และใน prompt
    - แปลงรหัสพิเศษของฟอนต์ไทยกลับเป็นตัวปกติ (ดูหัวไฟล์) — ทำที่นี่จึงครอบทั้งสอง engine
    """
    text = normalize_thai_pua("\n".join(parts)).replace("\x00", "")
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
