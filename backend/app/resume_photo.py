"""ดึงรูปโปรไฟล์จากหน้าแรกของเรซูเม่ — heuristic ล้วน ไม่มี LLM ไม่มี face detection.

**เดาผิดได้โดยธรรมชาติ**: เลือกจากขนาดกับสัดส่วนของรูปเท่านั้น เรซูเม่ที่ไม่มีรูปคนแต่มี
โลโก้หรือกราฟิกสี่เหลี่ยมใหญ่พอ จะได้กราฟิกนั้นมาแทน — ข้อจำกัดที่ยอมรับไว้ตั้งแต่ต้น ไม่ใช่บั๊ก
ส่วนหน้าเว็บที่ยังให้ HR ตัดสินผู้สมัคร รูปถูกซ่อนไว้เป็นค่าตั้งต้นอยู่แล้ว (app_settings
key `screening_photos`)

**รูปที่มีชั้นความโปร่งใส (soft mask):** Canva ส่งออกรูปโปรไฟล์เป็นแผ่นใหญ่ที่รูปคนกินแค่ส่วนหนึ่ง
ที่เหลือโปร่งใส (วัดจริง: แผ่น 1315×1452 มีส่วนมองเห็น 20%) — หยิบแค่ชั้นรูปโดยไม่ใช้ mask
ส่วนโปร่งใสจะกลายเป็นสีดำ รูปคนเหลือตัวเล็กบนพื้นดำ จึงวัดขนาดจากส่วนที่มองเห็นจริง และตัดรูปด้วย
การวาดเฉพาะบริเวณนั้นของหน้า (ได้ภาพตรงกับที่คนเห็นตอนเปิดไฟล์ รวมการผสมกับพื้นหลังแล้ว)

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

# ค่าความทึบใน mask ที่นับว่า "มองเห็น" (0-255) — ขอบนุ่มจาง ๆ ไม่นับ กันกรอบตัดกว้างเกินจริง
ALPHA_VISIBLE = 128
# ด้านยาวสุดของรูปที่วาดจากหน้า — พอสำหรับวงรูปบนหน้าเว็บ ไม่ต้องละเอียดเท่าต้นฉบับ
RENDER_MAX_PX = 800

_VISIBLE_TABLE = bytes(1 if v >= ALPHA_VISIBLE else 0 for v in range(256))


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


def visible_box(alpha: bytes, width: int, height: int) -> Optional[tuple[int, int, int, int]]:
    """กรอบของส่วนที่มองเห็นใน mask (x0, y0, x1, y1 แบบไม่รวมขอบขวา/ล่าง) หรือ None ถ้าโปร่งใสทั้งแผ่น.

    แปลง mask เป็น 0/1 ด้วย bytes.translate แล้วใช้ find/rfind ต่อแถว — ทำงานในระดับ C
    แผ่น 1315×1452 จึงเร็วพอโดยไม่ต้องพึ่ง numpy
    """
    flags = alpha.translate(_VISIBLE_TABLE)
    x0, y0, x1, y1 = width, -1, -1, -1
    for y in range(height):
        row = flags[y * width:(y + 1) * width]
        left = row.find(1)
        if left < 0:
            continue
        if y0 < 0:
            y0 = y
        y1 = y
        x0 = min(x0, left)
        x1 = max(x1, row.rfind(1))
    if y0 < 0:
        return None
    return x0, y0, x1 + 1, y1 + 1


def _sub_rect(rect, box: tuple[float, float, float, float]):
    """ส่วนของตำแหน่งที่วางรูปบนหน้า ตามสัดส่วนกรอบ (0-1) — รูปในเรซูเม่ไม่หมุน จึงแมปเชิงเส้นได้."""
    fx0, fy0, fx1, fy1 = box
    return pymupdf.Rect(
        rect.x0 + rect.width * fx0,
        rect.y0 + rect.height * fy0,
        rect.x0 + rect.width * fx1,
        rect.y0 + rect.height * fy1,
    )


def _measure(doc, page, img) -> Optional[dict]:
    """ขนาดที่มองเห็นจริงของรูปหนึ่งรูป + ตำแหน่งบนหน้า — None = โปร่งใสทั้งแผ่น."""
    xref, smask, width, height = img[0], img[1], img[2], img[3]
    frac = (0.0, 0.0, 1.0, 1.0)
    if smask:
        mask = pymupdf.Pixmap(doc, smask)
        box = visible_box(mask.samples, mask.width, mask.height)
        if box is None:
            return None
        # mask ละเอียดต่างจากรูปได้ จึงคิดเป็นสัดส่วนก่อน แล้วค่อยคูณกลับเป็นพิกเซลของรูป
        frac = (box[0] / mask.width, box[1] / mask.height,
                box[2] / mask.width, box[3] / mask.height)
    vis_w = round(width * (frac[2] - frac[0]))
    vis_h = round(height * (frac[3] - frac[1]))
    return {
        "xref": xref,
        "masked": bool(smask),
        "frac": frac,
        "w": vis_w,
        "h": vis_h,
        "rects": [_sub_rect(r, frac) for r in page.get_image_rects(xref)],
    }


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


def _render_visible(page, m: dict) -> Optional[tuple[bytes, str]]:
    """วาดเฉพาะส่วนที่มองเห็นของรูปจากหน้า PDF → JPEG (ไม่มีส่วนโปร่งใสให้กลายเป็นสีดำ).

    ความละเอียดใกล้ของต้นฉบับ แต่ด้านยาวไม่เกิน RENDER_MAX_PX
    """
    if not m["rects"]:
        return None
    clip = m["rects"][0]
    longest_pt = max(clip.width, clip.height)
    if longest_pt <= 0:
        return None
    target_px = min(max(m["w"], m["h"]), RENDER_MAX_PX)
    zoom = target_px / longest_pt
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False)
    return pix.tobytes("jpg", jpg_quality=85), "image/jpeg"


def extract_candidate_photo(pdf_bytes: bytes) -> Optional[tuple[bytes, str]]:
    """รูปที่น่าจะเป็นรูปโปรไฟล์จากหน้าแรก → (bytes, mime) หรือ None ถ้าไม่เจอที่เข้าเกณฑ์.

    ดูหน้าแรกหน้าเดียว — รูปโปรไฟล์ไม่อยู่หน้าอื่น และหน้าถัดไปมักมีแต่โลโก้ผลงาน
    เกณฑ์ (วัดจากส่วนที่มองเห็นจริง): ไม่เล็กเกิน · สัดส่วนใกล้ภาพคน · ไม่ได้วางเต็มหน้า —
    ในบรรดาที่ผ่าน เลือกรูปที่พื้นที่มากสุด
    อาจ raise ได้ (PDF เสีย) — ผู้เรียกต้องห่อ try/except เอง
    """
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        if doc.page_count == 0:
            return None
        page = doc[0]
        measured = [
            m
            for img in page.get_images(full=True)
            if (m := _measure(doc, page, img)) is not None
            and is_photo_candidate(m["w"], m["h"])
            and not covers_most_of_page(m["rects"], page.rect)
        ]
        best = max(measured, key=lambda m: m["w"] * m["h"], default=None)
        if best is None:
            return None
        # รูปมี mask → วาดส่วนที่มองเห็นจากหน้า · ไม่มี mask → ใช้ไบต์ต้นฉบับตรง ๆ (คมสุด)
        result = _render_visible(page, best) if best["masked"] else None
        if result is None:
            result = _to_browser_image(doc, best["xref"])
    if result is None or len(result[0]) > MAX_PHOTO_BYTES:
        return None
    return result
