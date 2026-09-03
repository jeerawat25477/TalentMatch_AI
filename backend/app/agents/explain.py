"""อธิบายที่มาของ fit score เป็นประโยคภาษาคน — **ไม่เรียก LLM**.

ตัวเลขที่ต้องใช้ (matched/missing ทั้งสองฝั่ง) ถูกคำนวณเสร็จแล้วใน matcher ซึ่งเป็น
deterministic node การ "อธิบาย" ตัวเลขที่มีอยู่จึงไม่ใช่การเทียบทักษะใหม่ ไม่ขัดกฎใน
CLAUDE.md ที่ห้าม matcher เทียบสตริงเอง — และการเรียก LLM ตรงนี้จะเปลืองโควตาฟรี
(20 call/วัน) โดยไม่ได้อะไรที่ template ทำไม่ได้

⚠️ สูตรคะแนนอยู่ที่ matcher.py ที่เดียว ไฟล์นี้ต้องไม่คำนวณคะแนนซ้ำ แค่บรรยายสิ่งที่เกิดขึ้น
"""

# ยกชื่อทักษะมาในประโยคได้ไม่เกินเท่านี้ ที่เหลือสรุปเป็น "และอีก N ข้อ"
# ไม่งั้นตำแหน่งที่มีเกณฑ์ 20 ข้อจะได้ประโยคยาวเป็นย่อหน้าจนไม่มีใครอ่าน
MAX_NAMED_SKILLS = 3


def _join(skills: list[str]) -> str:
    """รายชื่อทักษะแบบสั้น — เกิน MAX_NAMED_SKILLS แล้วตัดเหลือ "และอีก N ข้อ"."""
    if len(skills) <= MAX_NAMED_SKILLS:
        return ", ".join(skills)
    shown = ", ".join(skills[:MAX_NAMED_SKILLS])
    return f"{shown} และอีก {len(skills) - MAX_NAMED_SKILLS} ข้อ"


def _side(matched: list[str], missing: list[str], label: str) -> str:
    """บรรยายผลของฝั่งหนึ่ง (ต้องมี / อยากได้) — คืน "" ถ้า JD ไม่ได้ระบุฝั่งนั้น."""
    total = len(matched) + len(missing)
    if not total:
        return ""
    if not missing:
        return f"มี{label}ครบทุกข้อ ({total}/{total})"
    if not matched:
        return f"ไม่มี{label}เลยสักข้อ (0/{total}) — ขาด {_join(missing)}"
    return (
        f"ขาด{label} {len(missing)} จาก {total} ข้อ ({_join(missing)})"
    )


def explain_score(gaps: dict, fit_score: int) -> str:
    """ประโยคสรุปว่าทำไมถึงได้คะแนนนี้ — ใช้โชว์คู่กับตัวเลขบนหน้าเว็บ."""
    gaps = gaps or {}
    m_req = gaps.get("matched_required") or []
    x_req = gaps.get("missing_required") or []
    m_pref = gaps.get("matched_preferred") or []
    x_pref = gaps.get("missing_preferred") or []

    if not (m_req or x_req or m_pref or x_pref):
        # ตรงกับกรณีที่ matcher บังคับคะแนนเป็น REVIEW_FROM — ห้ามบอกว่า "ได้ N% เพราะ..."
        # เพราะคะแนนนี้ไม่ได้มาจากการเทียบทักษะเลย จะทำให้ HR เข้าใจผิด
        return (
            "ยังไม่มีเกณฑ์ทักษะใน JD ให้เทียบ จึงให้คะแนนกลางไว้รอคนตัดสิน "
            "— ลองตรวจว่าประกาศงานระบุทักษะที่ต้องการชัดเจนพอหรือยัง"
        )

    parts = [
        p
        for p in (
            _side(m_req, x_req, "ทักษะที่ต้องมี"),
            _side(m_pref, x_pref, "ทักษะที่อยากได้"),
        )
        if p
    ]

    # JD ระบุเกณฑ์แค่ฝั่งเดียว: matcher ให้สัดส่วนของอีกฝั่งเต็ม 1.0 (คะแนนส่วนนั้นได้ฟรี)
    # ถ้าไม่บอก ประโยคจะอ่านแล้วขัดกันเอง — เจอจริงกับ JD ที่ไม่มี preferred เลย
    # ผู้สมัครที่ตรงเกณฑ์ที่ต้องมี 0/19 ยังได้ 40% ซึ่ง HR อ่านแล้วงงว่ามาจากไหน
    # ⚠️ ไม่ระบุตัวเลขน้ำหนัก (60/40) ตรงนี้ เพราะสูตรอยู่ที่ matcher.py ที่เดียว
    missing_side = ""
    if not (m_req or x_req):
        missing_side = "ทักษะที่ต้องมี"
    elif not (m_pref or x_pref):
        missing_side = "ทักษะที่อยากได้"
    if missing_side:
        parts.append(f"JD ไม่ได้ระบุ{missing_side} คะแนนส่วนนั้นจึงถูกนับให้เต็ม")

    return f"ได้ {fit_score}% เพราะ" + " · ".join(parts)
