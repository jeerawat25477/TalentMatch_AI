"""แปลงไฟล์ PDF เป็นข้อความด้วย pdfplumber (ใช้ในขั้นอัปโหลด resume)."""
import io

import pdfplumber


def extract_text_from_pdf(data: bytes) -> str:
    """คืนข้อความรวมทุกหน้าจากไบต์ของไฟล์ PDF (เว้นบรรทัดคั่นระหว่างหน้า)."""
    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    # บาง PDF (ฟอนต์ฝังแบบแปลก ๆ) แกะข้อความออกมาปน NUL (0x00) — Postgres คอลัมน์ text
    # เก็บ NUL ไม่ได้ (DataError) ต้องล้างทิ้งที่ต้นทาง ครอบคลุมทั้งตอนอัปโหลดและ reprocess
    return "\n".join(parts).replace("\x00", "").strip()
