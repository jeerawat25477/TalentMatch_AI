"""ด่านตรวจหลักฐานทักษะ — ยืนยันว่าข้อความที่ LLM อ้างมามีอยู่จริงในเรซูเม่.

`resume_parser` ขอให้ LLM คืน `skill_evidence` = ประโยคจากเรซูเม่ที่เป็นที่มาว่าทำไมถึงนับว่า
ผู้สมัครมีทักษะนั้น แต่ LLM แต่งประโยคที่ "ฟังดูเหมือนอยู่ในเรซูเม่" ขึ้นเองได้เสมอ
และหลักฐานปลอมอันตรายกว่าไม่มีหลักฐาน เพราะ HR จะเชื่อโดยไม่กลับไปเปิดไฟล์จริง

โมดูลนี้จึงเป็นฟังก์ชันบริสุทธิ์ล้วน (ทดสอบได้แบบเดียวกับ `_is_unreadable_resume`) และ
`filter_evidence` ต้องถูกเรียก **ก่อน** ข้อมูลเข้าสู่ state — ของที่ยืนยันไม่ได้ต้องไม่มีวัน
ไปถึง DB หรือหน้าเว็บ

⚠️ ขอบเขต: ด่านนี้ตอบว่า "ข้อความนี้คัดลอกมาจากไฟล์จริงไหม" ไม่ได้ตอบว่า "ข้อความนี้
พิสูจน์ทักษะนั้นจริงไหม" — LLM ยกประโยคจริงมาผูกกับทักษะผิดตัวได้อยู่ และเกณฑ์ความคล้าย
แบบ fuzzy ยอมให้คำหรือตัวเลขเดียวเพี้ยนได้ (แลกกับการทนเรซูเม่ที่ฟอนต์พัง) ดู
tests/test_evidence.py::test_ขอบเขตที่ยอมรับว่ายังผ่าน
"""
import re
from difflib import SequenceMatcher

# ความคล้ายขั้นต่ำ (สัดส่วนของความยาว quote ที่หาเจอเป็นก้อนติดกันใน raw) ที่ยังถือว่า
# "คัดลอกมาจริง" — เผื่อ PDF ที่ตัดบรรทัดกลางคำหรือมีอักขระแปลกปนมา
EVIDENCE_MIN_RATIO = 0.8
# quote ที่ยาวกว่านี้แปลว่า LLM ยกมาทั้งย่อหน้า ไม่ใช่ "ประโยคอ้างอิง" — ทิ้ง เพราะยาวเกิน
# กว่าที่จะช่วย HR ตัดสินได้ และกินพื้นที่การ์ดจนอ่านไม่รู้เรื่อง
MAX_EVIDENCE_CHARS = 300

_WS = re.compile(r"\s+")


def _normalize(s: str) -> str:
    """ตัวเล็ก + ยุบช่องว่างทุกชนิดเป็นช่องว่างเดียว.

    ต้องยุบ whitespace เพราะข้อความที่สกัดจาก PDF มีบรรทัดขาดกลางประโยคเป็นปกติ
    ถ้าเทียบดิบ ๆ หลักฐานที่ถูกต้องจะตกเกือบหมด
    """
    return _WS.sub(" ", (s or "").lower()).strip()


def verify_evidence(quote: str, raw_text: str) -> bool:
    """ข้อความ `quote` คัดลอกมาจาก `raw_text` จริงหรือไม่."""
    q = _normalize(quote)
    raw = _normalize(raw_text)
    if not q or not raw:
        return False
    if len(quote) > MAX_EVIDENCE_CHARS:
        return False

    # ทางลัด: ปกติ LLM คัดลอกมาตรง ๆ อยู่แล้ว ไม่ต้องเสียเวลา diff
    if q in raw:
        return True

    # ⚠️ autojunk=False จำเป็น: ค่าเริ่มต้นจะมองอักขระที่พบบ่อยในลำดับยาวเกิน 200 ตัวเป็น
    # "junk" แล้วข้ามไป ซึ่งเรซูเม่ทั้งฉบับยาวเกินนั้นเสมอ — ผลเทียบจะเพี้ยนแบบเงียบ ๆ
    anchor = SequenceMatcher(None, q, raw, autojunk=False).find_longest_match(
        0, len(q), 0, len(raw)
    )
    if not anchor.size:
        return False

    # เทียบกับ "หน้าต่างเดียว" ของเรซูเม่ที่ยาวเท่า quote โดยจัดตำแหน่งจากก้อนที่ยาวที่สุด
    # แทนที่จะวัดจากก้อนนั้นก้อนเดียว (พิมพ์ผิดกลางประโยคจะหั่นก้อนเป็นสองท่อน ของจริงจะตก)
    # และแทนที่จะรวมทุกก้อนทั่วทั้งไฟล์ (ข้อความที่แต่งขึ้นจะเก็บตัวอักษรกระจาย ๆ มาจนผ่าน)
    start = max(0, anchor.b - anchor.a)
    window = raw[start : start + len(q)]
    return SequenceMatcher(None, q, window, autojunk=False).ratio() >= EVIDENCE_MIN_RATIO


def filter_evidence(
    evidence: dict[str, str], skills: list[str], raw_text: str
) -> dict[str, str]:
    """คัดเหลือเฉพาะหลักฐานที่เชื่อถือได้ — ที่เหลือทิ้งทั้งหมด ไม่เก็บลง state/DB.

    ทิ้งเมื่อ: ชื่อทักษะไม่ได้อยู่ในรายการ `skills` ที่ LLM คืนมาเอง (มโนชื่อทักษะเพิ่ม),
    ข้อความว่าง, หรือยืนยันกับเรซูเม่จริงไม่ผ่าน
    """
    if not evidence or not isinstance(evidence, dict):
        return {}
    # เทียบชื่อทักษะแบบ normalize เพราะ LLM มักคืน "Docker " หรือ "docker" ไม่ตรงตัวพิมพ์
    # ค่าใน dict คือการสะกดต้นฉบับ เพื่อให้ key ที่คืนออกไปตรงกับ parsed_resume.skills เป๊ะ
    allowed = {_normalize(s): s for s in skills if s and s.strip()}

    kept: dict[str, str] = {}
    for key, quote in evidence.items():
        skill = allowed.get(_normalize(str(key)))
        if skill is None or not isinstance(quote, str) or not quote.strip():
            continue
        if verify_evidence(quote, raw_text):
            kept[skill] = quote.strip()
    return kept
