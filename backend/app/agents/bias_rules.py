"""ด่านกฎตายตัวของตัวตรวจอคติ — จับถ้อยคำชัด ๆ ในประกาศงานโดยไม่ใช้ LLM.

ทำไมต้องมีทั้งที่ bias_auditor ใช้ LLM อยู่แล้ว: LLM ตอบไม่เหมือนกันทุกรอบ ประกาศเดียวกันเคย
ได้คำอธิบายสามแบบ และมีโอกาสตอบ "passed" ทั้งที่ประกาศเขียน "เพศชาย" ไว้ตรง ๆ คำพวกนี้จับด้วย
regex ได้แน่นอนทุกครั้งและไม่เสียเงิน ส่วน LLM ยังเรียกหนึ่งครั้งเท่าเดิมเพื่อดูเคสที่ซ่อนกว่านี้

**เข้มเรื่อง false positive เป็นหลักการแรก** — คำเตือนที่ไม่จริงทำให้ HR เลิกเชื่อคำเตือนทั้งหมด
(หลักเดียวกับ nodes/jd_reviewer.py) จึงจับเฉพาะรูปที่มีความหมายเดียว และปล่อยคำกำกวมให้ LLM:
- "บุคลิกดี" มักหมายถึงการวางตัว ไม่ใช่หน้าตา
- "single" ชนกับ "Single Page Application"
- "native speaker" อาจจำเป็นจริงกับงานแปล
- "ชาย" เดี่ยว ๆ ชนกับ "ชายฝั่ง"
- "อายุงาน N ปี" คือประสบการณ์ ไม่ใช่อายุคน

ทุก phrase ที่คืนเป็น substring ของข้อความต้นฉบับเสมอ — HR ต้องค้นเจอในประกาศของตัวเองได้
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RuleHit:
    category: str
    phrase: str


# คำที่ทำให้ถ้อยคำถัดจากมัน "ไม่ใช่การกีดกัน" เช่น "ไม่จำกัดเพศ อายุ เชื้อชาติ ศาสนา" หรือ
# "รับทั้งโสดและสมรส" — ใช้เฉพาะรูปแบบที่เป็นคำหมวดล้วน ๆ (guard=True) รูปแบบที่มีตัวเลขเกณฑ์
# อย่าง "อายุไม่เกิน 30 ปี" ไม่ใช้ เพราะ "ไม่จำกัดเพศ อายุไม่เกิน 30 ปี" ยังกีดกันเรื่องอายุอยู่
_NEGATIONS = (
    "ไม่จำกัด", "ไม่แบ่งแยก", "ไม่คำนึง", "ไม่เลือกปฏิบัติ", "ทั้ง",
    "regardless", "without regard", "equal opportunit",
    # "เพศชายหรือเพศหญิง" — lookahead กันตัวแรกไว้แล้ว ส่วนตัวหลังกันด้วยคำนำหน้าชุดนี้
    "ชายหรือ", "ชายและ", "ชาย/", "หญิงหรือ", "หญิงและ", "หญิง/",
)
_GUARD_WINDOW = 20

_TH_UNIT_CM = r"(?:\s*(?:ซม\.?|เซนติเมตร|cm))"
_TH_UNIT_KG = r"(?:\s*(?:กก\.?|กิโลกรัม|kg))"
_RANGE = r"(?:\s*(?:-|–|~|ถึง|to)\s*\d{2})"

# (หมวด, regex, guard) — ลำดับไม่มีผลกับผลลัพธ์ ผลเรียงตามตำแหน่งในประกาศ
_RULES: list[tuple[str, str, bool]] = [
    # ── เพศ ── ห้ามจับ "เพศชายหรือเพศหญิง" (รับทั้งสองเพศ) จึงมี lookahead
    ("เพศ", r"เพศ\s*(?:ชาย|หญิง)(?!\s*(?:หรือ|และ|/|,)\s*(?:เพศ)?\s*(?:ชาย|หญิง))", True),
    ("เพศ", r"(?:รับ)?เฉพาะ\s*(?:เพศ)?\s*(?:ผู้ชาย|ผู้หญิง|ชาย(?!ฝั่ง|หาด|แดน)|หญิง)", False),
    ("เพศ", r"\b(?:male|female)s?\s+(?:candidates?\s+)?only\b", False),
    ("เพศ", r"\bgender\s*:\s*(?:male|female)\b", False),
    # ── อายุ ── ต้องมีตัวเลขสองหลักเสมอ ("อายุงาน 2 ปี" ไม่ผ่านเพราะคำถัดจาก "อายุ" คือ "งาน")
    ("อายุ", r"อายุ\s*(?:ไม่เกิน|ไม่ต่ำกว่า|ไม่น้อยกว่า|ตั้งแต่|ระหว่าง|ต่ำกว่า)\s*\d{2}" + _RANGE + r"?(?:\s*ปี)?", False),
    ("อายุ", r"อายุ\s*\d{2}" + _RANGE + r"(?:\s*ปี)?", False),
    ("อายุ", r"อายุ\s*\d{2}\s*ปี(?:\s*ขึ้นไป)?", False),
    ("อายุ", r"\baged?\s*(?::\s*)?(?:under|below|not over|between|over)?\s*\d{2}" + _RANGE + r"?\b", False),
    ("อายุ", r"\bunder\s+\d{2}\s+years?\s+old\b", False),
    # ── สถานภาพสมรส ──
    ("สถานภาพสมรส", r"สถานภาพ\s*(?:โสด|สมรส)", True),
    ("สถานภาพสมรส", r"โสด", True),
    ("สถานภาพสมรส", r"ยังไม่(?:แต่งงาน|สมรส)", False),
    ("สถานภาพสมรส", r"ไม่มีบุตร", False),
    ("สถานภาพสมรส", r"ไม่มีภาระ(?:ทาง)?ครอบครัว", False),
    ("สถานภาพสมรส", r"\bmarital\s+status\b", True),
    ("สถานภาพสมรส", r"\bunmarried\b", False),
    # ── รูปลักษณ์ ── ส่วนสูง/น้ำหนักต้องมีตัวเลขและหน่วย ไม่งั้น "สูง" ชนคำอื่นเยอะเกินไป
    ("รูปลักษณ์", r"ส่วนสูง\s*(?:ไม่ต่ำกว่า|ตั้งแต่|ขั้นต่ำ)?\s*\d{3}" + _TH_UNIT_CM + r"?", False),
    ("รูปลักษณ์", r"สูง\s*(?:ไม่ต่ำกว่า|ตั้งแต่)?\s*\d{3}" + _TH_UNIT_CM, False),
    ("รูปลักษณ์", r"น้ำหนัก\s*(?:ไม่เกิน|ไม่ต่ำกว่า)?\s*\d{2,3}" + _TH_UNIT_KG, False),
    ("รูปลักษณ์", r"หน้าตาดี|รูปร่างดี|รูปร่างสมส่วน|ผิวขาว", False),
    ("รูปลักษณ์", r"\bgood[- ]looking\b|\battractive appearance\b", False),
    # ── ความพิการ/สภาพร่างกาย ──
    ("ความพิการ", r"ไม่มีความพิการ|ไม่พิการ", False),
    ("ความพิการ", r"ร่างกายสมบูรณ์", False),
    ("ความพิการ", r"(?:อวัยวะ|ร่างกาย)ครบ(?:\s*(?:32|๓๒|สามสิบสอง))?", False),
    ("ความพิการ", r"\bable[- ]bodied\b|\bno disabilit(?:y|ies)\b", False),
    # ── เชื้อชาติ/สัญชาติ/ภูมิลำเนา ── "สัญชาติไทย" เฉย ๆ ไม่จับ (บางงานกฎหมายบังคับจริง)
    ("เชื้อชาติ/สัญชาติ", r"เชื้อชาติ\s*(?:ไทย|จีน)", True),
    ("เชื้อชาติ/สัญชาติ", r"สัญชาติ\s*[^\s,.]{1,12}?\s*เท่านั้น", False),
    ("เชื้อชาติ/สัญชาติ", r"ภูมิลำเนา\s*(?:อยู่\s*)?(?:ใน|จังหวัด)\s*[^\s,.]{1,15}", False),
    ("เชื้อชาติ/สัญชาติ", r"\b(?:thai|chinese)\s+nationals?\s+only\b", False),
    # ── ศาสนา ──
    ("ศาสนา", r"(?:นับถือ\s*)?ศาสนา\s*(?:พุทธ|คริสต์|อิสลาม|ฮินดู)", True),
    ("ศาสนา", r"\b(?:christian|muslim|buddhist)s?\s+only\b", False),
    ("ศาสนา", r"\breligion\s*:\s*\w+", True),
    # ── สถาบันการศึกษา ── ชื่อมหาวิทยาลัยเฉพาะไม่จับ (มีเหตุผลได้หลายแบบ ให้ LLM ตัดสิน)
    ("สถาบันการศึกษา", r"(?:มหาวิทยาลัย|สถาบัน)\s*(?:ชั้นนำ|ของรัฐ|ดัง|มีชื่อเสียง)", False),
    ("สถาบันการศึกษา", r"\btop[- ](?:tier\s+)?universit(?:y|ies)\b", False),
    ("สถาบันการศึกษา", r"\b(?:ivy league|prestigious universit(?:y|ies))\b", False),
]

_COMPILED = [(cat, re.compile(pat, re.IGNORECASE), guard) for cat, pat, guard in _RULES]


def _negated(text: str, start: int) -> bool:
    """มีคำปฏิเสธนำหน้าในบรรทัดเดียวกันภายใน _GUARD_WINDOW ตัวอักษรหรือไม่."""
    line_start = text.rfind("\n", 0, start) + 1
    before = text[max(line_start, start - _GUARD_WINDOW):start].lower()
    return any(neg in before for neg in _NEGATIONS)


def find_biased_phrases(text: str) -> list[RuleHit]:
    """ถ้อยคำที่เข้าข่ายอคติในประกาศ เรียงตามตำแหน่ง ไม่ซ้ำ และไม่ซ้อนกัน.

    รูปแบบหลายตัวจับช่วงเดียวกันได้ (เช่น "สถานภาพโสด" กับ "โสด") จึงเก็บช่วงที่ยาวที่สุด
    ของแต่ละตำแหน่ง แล้วทิ้งช่วงที่ทับกับช่วงที่เก็บไปแล้ว
    """
    if not text:
        return []
    spans: list[tuple[int, int, str]] = []
    for cat, rx, guard in _COMPILED:
        for m in rx.finditer(text):
            if guard and _negated(text, m.start()):
                continue
            spans.append((m.start(), m.end(), cat))

    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    hits: list[RuleHit] = []
    seen: set[str] = set()
    last_end = -1
    for start, end, cat in spans:
        if start < last_end:
            continue
        phrase = text[start:end].strip()
        last_end = end
        if phrase and phrase not in seen:
            seen.add(phrase)
            hits.append(RuleHit(cat, phrase))
    return hits


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


# คำเชื่อมที่เหลือค้างหลังตัดถ้อยคำของกฎออกจากข้อของ LLM ("เพศหญิง และบุคลิกดี" → "และบุคลิกดี")
_CONNECTORS = ("และ", "หรือ", "กับ", "รวมถึง", ",", "/", "、", "·", "-", ";", ":", "(", ")", "and", "or")
# เศษที่สั้นกว่านี้ไม่ใช่ถ้อยคำ แค่ตัวอักษรตกค้าง
_MIN_REST_CHARS = 3


def _trim_connectors(s: str) -> str:
    changed = True
    while changed and s:
        changed = False
        for c in _CONNECTORS:
            if s.startswith(c):
                s, changed = s[len(c):], True
            if s.endswith(c):
                s, changed = s[: -len(c)], True
    return s


def _verbatim(squashed: str, raw_jd: str) -> str | None:
    """หาข้อความในประกาศที่ตัดช่องว่างแล้วตรงกับ squashed — คืนตามตัวสะกดและช่องว่างเดิม."""
    if not squashed or not raw_jd:
        return None
    pattern = r"\s*".join(re.escape(ch) for ch in squashed)
    m = re.search(pattern, raw_jd, re.IGNORECASE)
    return m.group(0).strip() if m else None


def merge_criteria(llm_items: list[str], hits: list[RuleHit], raw_jd: str = "") -> list[str]:
    """รวมรายการของ LLM กับของกฎ ให้ได้ถ้อยคำทีละเรื่อง ไม่ซ้ำความหมาย.

    **ถ้อยคำของกฎเป็นหน่วยหลัก** เพราะกฎยกข้อความจากประกาศตรงตัวและจับทีละเรื่องเสมอ
    ซึ่งคือหน่วยที่ HR ยืนยัน "จำเป็นกับงานนี้" ทีละข้อ (app/bias_ack.py) เดิมเก็บของ LLM เมื่อทับกัน
    แล้ว LLM รวม "เพศหญิง อายุไม่เกิน 35 ปี" เป็นข้อเดียว — การยืนยันครั้งเดียวจึงครอบทั้งเพศและอายุ
    ทั้งที่งานอาจจำเป็นแค่เรื่องเดียว (เจอจากการลองจริง 2026-09-28)

    1. ถ้อยคำของกฎทั้งหมด ตามลำดับในประกาศ
    2. ข้อของ LLM ที่ไม่ทับกฎเลย → เก็บ (เรื่องที่กฎจับไม่ได้)
    3. ข้อของ LLM ที่ทับกฎ → ตัดส่วนที่กฎครอบออก เศษที่เหลือเก็บต่อเมื่อยาวพอและ **ปรากฏตรงตัว
       ในประกาศ** — กันคำสรุปที่ LLM แต่งเองกลายเป็นถ้อยคำที่ HR ต้องไปยืนยัน
       ข้อของ LLM ที่สั้นกว่า/เท่ากับถ้อยคำของกฎ ("อายุไม่เกิน 30") ถือว่ากฎครอบแล้ว
    """
    merged: list[str] = []
    keys: list[str] = []

    def add(phrase: str) -> None:
        k = _squash(phrase)
        if k and k not in keys:
            merged.append(phrase)
            keys.append(k)

    for hit in hits:
        add(hit.phrase)
    rule_keys = [_squash(h.phrase) for h in hits]

    for item in llm_items:
        item = (item or "").strip()
        k = _squash(item)
        if not k:
            continue
        inside = [r for r in rule_keys if r in k]
        if any(k in r for r in rule_keys):
            continue  # กฎครอบทั้งข้อแล้ว
        if not inside:
            add(item)
            continue
        rest = k
        for r in sorted(inside, key=len, reverse=True):
            rest = rest.replace(r, "\x00")
        for piece in rest.split("\x00"):
            piece = _trim_connectors(piece)
            if len(piece) >= _MIN_REST_CHARS:
                found = _verbatim(piece, raw_jd)
                if found:
                    add(found)
    return merged


def categories(hits: list[RuleHit]) -> list[str]:
    """หมวดที่พบ เรียงตามลำดับที่เจอครั้งแรก ไม่ซ้ำ."""
    out: list[str] = []
    for h in hits:
        if h.category not in out:
            out.append(h.category)
    return out
