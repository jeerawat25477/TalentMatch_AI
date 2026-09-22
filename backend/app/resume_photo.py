"""ดึงรูปโปรไฟล์จากหน้าแรกของเรซูเม่ — heuristic ล้วน ไม่มี LLM ไม่มี face detection.

**เดาผิดได้โดยธรรมชาติ**: เลือกจากขนาดกับสัดส่วนของรูปเท่านั้น เรซูเม่ที่ไม่มีรูปคนแต่มี
โลโก้หรือกราฟิกสี่เหลี่ยมใหญ่พอ จะได้กราฟิกนั้นมาแทน — ข้อจำกัดที่ยอมรับไว้ตั้งแต่ต้น ไม่ใช่บั๊ก
ส่วนหน้าเว็บที่ยังให้ HR ตัดสินผู้สมัคร รูปถูกซ่อนไว้เป็นค่าตั้งต้นอยู่แล้ว (app_settings
key `screening_photos`)

ฟังก์ชันบริสุทธิ์: รับไบต์ คืนไบต์ ไม่แตะ DB — ผู้เรียก (resume_ingest) เป็นคนบันทึก
"""
import logging
from typing import Optional

import pymupdf

log = logging.getLogger(__name__)

# เล็กกว่านี้ (ด้านใดด้านหนึ่ง) = ไอคอนโทรศัพท์/อีเมล/โลโก้เล็ก ไม่ใช่รูปคน
MIN_PHOTO_DIMENSION_PX = 80
# สัดส่วนกว้าง:สูงที่รับ — รูปติดบัตร/รูปครอปวงกลมอยู่ช่วงนี้ แถบแบนเนอร์และเส้นคั่นไม่อยู่
MIN_ASPECT = 0.6
MAX_ASPECT = 1.3
# รูปที่วางกินพื้นที่เกินครึ่งหน้า = ภาพสแกนทั้งหน้าหรือพื้นหลัง ไม่ใช่รูปโปรไฟล์ — วัดจริง:
# รูปโปรไฟล์ในเรซูเม่จริงกิน ~5% ของหน้า ส่วนเรซูเม่สแกนกิน 100% (สัดส่วน A4 ≈ 0.71 ผ่านเกณฑ์
# สัดส่วนข้างบนพอดี จึงต้องมีด่านนี้แยก)
MAX_PAGE_COVER = 0.5
# รูปใหญ่เกินนี้ไม่เก็บ — กันไฟล์ที่ฝังภาพความละเอียดสูงมาจน DB บวม (รูปโปรไฟล์ไม่ต้องใหญ่ขนาดนี้)
MAX_PHOTO_BYTES = 2 * 1024 * 1024

# รูปแบบที่เบราว์เซอร์แสดงได้ตรง ๆ — แบบอื่น (jpx, jbig2, ...) แปลงเป็น PNG ก่อน
_BROWSER_SAFE = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png"}


def is_photo_candidate(width: int, height: int) -> bool:
    """ขนาดกับสัดส่วนนี้น่าจะเป็นรูปคนไหม (ตัดไอคอนเล็กและแถบยาวทิ้ง)."""
    if width < MIN_PHOTO_DIMENSION_PX or height < MIN_PHOTO_DIMENSION_PX:
        return False
    return MIN_ASPECT <= width / height <= MAX_ASPECT


def covers_most_of_page(image_rects, page_rect) -> bool:
    """รูปนี้ถูกวางเต็มหน้าหรือเกือบเต็มไหม (ดูตำแหน่งที่วางจริงบนหน้า ไม่ใช่ขนาดพิกเซล).

    รูปที่ไม่รู้ตำแหน่ง (เช่นซ้อนอยู่ใน form XObject) ไม่ตัดทิ้ง — ไม่มีข้อมูลก็ไม่เดาว่าเป็นพื้นหลัง
    """
    page_area = page_rect.width * page_rect.height
    if page_area <= 0:
        return False
    return any(r.width * r.height / page_area > MAX_PAGE_COVER for r in image_rects)


def _to_browser_image(doc, xref: int) -> Optional[tuple[bytes, str]]:
    """ไบต์รูปใน PDF → (bytes, mime) ที่เบราว์เซอร์เปิดได้."""
    info = doc.extract_image(xref)
    if not info or not info.get("image"):
        return None
    mime = _BROWSER_SAFE.get((info.get("ext") or "").lower())
    if mime:
        return info["image"], mime
    # รูปแบบที่เบราว์เซอร์ไม่รู้จัก → วาดใหม่เป็น PNG (CMYK/สีพิเศษแปลงเป็น RGB ก่อน)
    pix = pymupdf.Pixmap(doc, xref)
    if pix.n - pix.alpha >= 4:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    return pix.tobytes("png"), "image/png"


def extract_candidate_photo(pdf_bytes: bytes) -> Optional[tuple[bytes, str]]:
    """รูปที่น่าจะเป็นรูปโปรไฟล์จากหน้าแรก → (bytes, mime) หรือ None ถ้าไม่เจอที่เข้าเกณฑ์.

    ดูหน้าแรกหน้าเดียว — รูปโปรไฟล์ไม่อยู่หน้าอื่น และหน้าถัดไปมักมีแต่โลโก้ผลงาน
    เกณฑ์: ไม่เล็กเกิน · สัดส่วนใกล้ภาพคน · ไม่ได้วางเต็มหน้า — ในบรรดาที่ผ่าน เลือกรูปที่
    พื้นที่พิกเซลมากสุด
    อาจ raise ได้ (PDF เสีย) — ผู้เรียกต้องห่อ try/except เอง
    """
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        if doc.page_count == 0:
            return None
        # (xref, smask, width, height, bpc, colorspace, ...) — ขนาดเป็นพิกเซลของรูปจริง
        page = doc[0]
        images = [
            img
            for img in page.get_images(full=True)
            if is_photo_candidate(img[2], img[3])
            and not covers_most_of_page(page.get_image_rects(img[0]), page.rect)
        ]
        best = max(
            images,
            key=lambda img: img[2] * img[3],
            default=None,
        )
        if best is None:
            return None
        result = _to_browser_image(doc, best[0])
    if result is None or len(result[0]) > MAX_PHOTO_BYTES:
        return None
    return result
