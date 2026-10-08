"""การยืนยันของ HR ว่าถ้อยคำที่ตัวตรวจอคติเตือน "จำเป็นกับงานนี้จริง".

บางงานเพศหรือสัญชาติเป็นคุณสมบัติที่จำเป็นจริง (เจ้าหน้าที่ตรวจค้นตัวผู้หญิง, อาชีพที่กฎหมาย
สงวนให้คนไทย) ถ้าไม่มีทางยืนยัน ⚠ จะขึ้นในหน้าผู้สมัครทุกคนตลอดไป เตือนซ้ำเรื่องที่ตัดสินแล้ว
นานไปคนจะเลิกอ่านคำเตือนทั้งหมด การยืนยันจึงต้อง

- **ทีละถ้อยคำ** — "เพศหญิง" จำเป็นไม่ได้แปลว่า "อายุไม่เกิน 30" ในประกาศเดียวกันจำเป็นด้วย
- **มีเหตุผล** อย่างน้อย MIN_REASON_CHARS ตัวอักษร กันการกดผ่านด้วย "ok"
- **รู้ว่าใคร เมื่อไร** — ชื่อมาจาก token ที่ล็อกอิน ไม่ใช่ค่าที่หน้าเว็บส่งมา
- **ไม่แตะคะแนน** — ถ้อยคำพวกนี้ไม่อยู่ในคะแนนอยู่แล้ว การยืนยันเปลี่ยนแค่สิ่งที่ HR เห็น
  ยกเว้นถ้อยคำที่ HR ใส่เป็นทักษะในเกณฑ์ด้วย: ต้องยืนยันก่อนถึงบันทึกเกณฑ์ได้ (biased_skills)
  และถอนไม่ได้ตราบที่ทักษะนั้นยังอยู่ในเกณฑ์ — การ์ดโชว์ป้าย "นับเป็นทักษะในคะแนน" (scored)

ฟังก์ชันบริสุทธิ์ทั้งไฟล์ ทดสอบได้โดยไม่ต่อ DB
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.agents.bias_rules import find_biased_phrases
from app.agents.skills import alternatives

MIN_REASON_CHARS = 10
MAX_REASON_CHARS = 500


class AckError(ValueError):
    """คำขอยืนยันที่รับไม่ได้ — router แปลงเป็น 422 พร้อมข้อความนี้."""


def validate_acks(
    requested: list[dict[str, str]],
    jd_criteria: list[str],
    user: str,
    now: datetime,
    previous: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """คำขอจากหน้าเว็บ → รายการที่จะเก็บ.

    - รับเฉพาะถ้อยคำที่อยู่ในผลตรวจจริง ถ้อยคำที่แต่งมาเองถูกทิ้ง (ยืนยันของที่ไม่เคยถูกเตือนไม่มีความหมาย)
    - ถ้อยคำซ้ำเก็บอันแรก
    - ถ้อยคำที่เคยยืนยันไว้แล้วด้วยเหตุผลเดิม คง by/at เดิมไว้ — แก้รายการอื่นต้องไม่ทำให้ดูเหมือน
      คนล่าสุดเป็นคนยืนยันทุกข้อ
    """
    allowed = set(jd_criteria)
    before = {a["phrase"]: a for a in (previous or [])}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in requested:
        phrase = (item.get("phrase") or "").strip()
        if phrase not in allowed or phrase in seen:
            continue
        reason = " ".join((item.get("reason") or "").split())
        if len(reason) < MIN_REASON_CHARS:
            raise AckError(
                f"ใส่เหตุผลว่าทำไม “{phrase}” จำเป็นกับงานนี้ อย่างน้อย {MIN_REASON_CHARS} ตัวอักษร"
            )
        reason = reason[:MAX_REASON_CHARS]
        old = before.get(phrase)
        if old and old.get("reason") == reason:
            out.append(old)
        else:
            out.append({"phrase": phrase, "reason": reason, "by": user, "at": now.isoformat()})
        seen.add(phrase)
    return out


def bias_view(
    jd_audit: dict[str, Any] | None,
    acks: list[dict[str, Any]] | None,
    skill_criteria: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """ผลตรวจของตำแหน่งแยกเป็น "ยังเตือนอยู่" กับ "HR ยืนยันแล้ว" — ใช้ทั้งหน้าตำแหน่งและหน้าผู้สมัคร.

    None = ตำแหน่งยังไม่มีผลตรวจ (หน้าผู้สมัครถอยไปใช้ audit_log ของผลประเมินเดิม)
    status = "flagged" ก็ต่อเมื่อยังมีถ้อยคำค้างเตือน หรือ LLM เตือนเรื่องที่ไม่ใช่ถ้อยคำ
    (เกณฑ์ทักษะที่มีอคติ) ซึ่งการยืนยันถ้อยคำไม่ได้ครอบคลุม
    """
    if not jd_audit:
        return None
    criteria = list(jd_audit.get("jd_criteria") or [])
    by_phrase = {a["phrase"]: a for a in (acks or []) if a.get("phrase") in criteria}
    pending = [c for c in criteria if c not in by_phrase]
    scored = scored_phrases(
        (skill_criteria or {}).get("required_skills") or [],
        (skill_criteria or {}).get("preferred_skills") or [],
        criteria,
    )
    acknowledged = [{**by_phrase[c], "scored": c in scored} for c in criteria if c in by_phrase]
    skills = list(jd_audit.get("biased_required_skills") or []) + list(
        jd_audit.get("biased_preferred_skills") or []
    )
    flagged_other = jd_audit.get("status") == "flagged" and not criteria
    log = jd_audit.get("log") or ""
    return {
        "status": "flagged" if (pending or skills or flagged_other) else "passed",
        "summary": log.split("\n")[0],
        "pending": pending,
        "acknowledged": acknowledged,
        "biased_skills": skills,
        "llm_checked": bool(jd_audit.get("llm_checked")),
    }


# ---------- ทักษะในเกณฑ์คะแนนที่ตรงกับอคติ ----------
# ช่องโหว่ที่เจอ 2026-10-07: AI ตรวจรายการทักษะตอนกด "วิเคราะห์" เท่านั้น แต่ HR พิมพ์ทักษะเพิ่มเองได้
# ทั้งในขั้นยืนยันเกณฑ์และตอนแก้เกณฑ์ทีหลัง — "Native English speaker" ที่ jd_analyzer กรองทิ้งไปแล้ว
# จึงกลับเข้าคะแนนได้โดยไม่มีอะไรเตือนหรือตัด · ทักษะแบบนี้จะนับคะแนนได้ก็ต่อเมื่อ HR ยืนยันถ้อยคำนั้น

# ทักษะต้องยาวอย่างน้อยกี่ส่วนของถ้อยคำที่ถูกเตือน ถึงจะนับว่าเป็นถ้อยคำเดียวกัน — กัน "ภาษาอังกฤษ"
# (ทักษะจริง) โดนจับเพราะบังเอิญอยู่ใน "เป็นเจ้าของภาษาอังกฤษ" (ภาษาไทยไม่เว้นวรรค เทียบระดับคำไม่ได้)
SKILL_PHRASE_COVERAGE = 0.6

_NORM = re.compile(r"[^0-9a-z#+฀-๿]+")


def _norm(text: str) -> str:
    # ไม่ใช้ skills.canonical: มันลบวงเล็บพร้อมข้อความข้างใน "(Native English speaker)" จะหายไปทั้งก้อน
    return _NORM.sub(" ", (text or "").lower()).strip()


def _variants(phrase: str) -> list[str]:
    """ถ้อยคำหนึ่งอาจมีสองภาษา "เป็นเจ้าของภาษาอังกฤษ (Native English speaker)" — แยกส่วนในวงเล็บ."""
    parts = [_norm(p) for p in re.split(r"[()（）]", phrase or "")]
    whole = _norm(phrase)
    return [v for v in dict.fromkeys([whole, *parts]) if v]


def _same_phrase(skill: str, phrase: str) -> bool:
    s = _norm(skill)
    if not s:
        return False
    for v in _variants(phrase):
        if s == v or f" {v} " in f" {s} ":
            return True
        if s in v and len(s) >= SKILL_PHRASE_COVERAGE * len(v):
            return True
    return False


def biased_skills(
    required: list[str],
    preferred: list[str],
    jd_criteria: list[str] | None,
    acks: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """ทักษะในเกณฑ์ที่ตรงกับอคติ และ HR ยังไม่ได้ยืนยันถ้อยคำนั้น — ฟังก์ชันบริสุทธิ์ ไม่เรียก AI.

    ทักษะหนึ่งข้อ (หรือตัวเลือกหนึ่งในกลุ่ม "A | B") ถูกจับเมื่อ
    - ตรงกับถ้อยคำที่ตัวตรวจเตือนในประกาศ (`jd_criteria`) → phrase = ถ้อยคำนั้น ยืนยันได้
    - หรือตัวทักษะเองเข้ากฎอคติ (bias_rules) แต่ไม่มีถ้อยคำในประกาศให้ยืนยัน → phrase = None ต้องลบออก
    คืน [{skill, side: "required"|"preferred", phrase}] ตามลำดับในเกณฑ์
    """
    criteria = [c for c in (jd_criteria or []) if c]
    acked = {a.get("phrase") for a in (acks or [])}
    out: list[dict[str, Any]] = []
    for side, skills in (("required", required or []), ("preferred", preferred or [])):
        for skill in skills:
            options = alternatives(skill) or [skill]
            phrase = next(
                (c for c in criteria for opt in options if _same_phrase(opt, c)), None
            )
            if phrase is None and not any(find_biased_phrases(opt) for opt in options):
                continue
            if phrase is not None and phrase in acked:
                continue
            out.append({"skill": skill, "side": side, "phrase": phrase})
    return out


def scored_phrases(required: list[str], preferred: list[str], jd_criteria: list[str] | None) -> set[str]:
    """ถ้อยคำที่ถูกเตือนซึ่งตอนนี้เป็นทักษะในเกณฑ์คะแนนด้วย (ไม่สนว่ายืนยันหรือยัง)."""
    options = [o for s in (*(required or []), *(preferred or [])) for o in (alternatives(s) or [s])]
    return {c for c in (jd_criteria or []) if c and any(_same_phrase(o, c) for o in options)}


def withdraw_blocked(
    required: list[str],
    preferred: list[str],
    jd_criteria: list[str] | None,
    previous: list[dict[str, Any]] | None,
    new: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """ทักษะที่จะ "หลุดการยืนยัน" ถ้ารับการยืนยันชุดใหม่ — ถอนถ้อยคำที่ยังเป็นทักษะในเกณฑ์ไม่ได้
    เพราะทักษะนั้นจะถูกนับคะแนนต่อโดยไม่มีใครยืนยัน (ช่องโหว่เดิมกลับมาทางประตูหลัง)
    คืนเฉพาะที่เพิ่งเกิดจากการถอนครั้งนี้ ของที่ค้างอยู่ก่อนแล้ว (ตำแหน่งเก่า) ไม่ขวางการยืนยันข้ออื่น
    """
    before = {(f["skill"], f["phrase"]) for f in biased_skills(required, preferred, jd_criteria, previous)}
    return [
        f for f in biased_skills(required, preferred, jd_criteria, new)
        if (f["skill"], f["phrase"]) not in before
    ]


def strip_skills(required: list[str], preferred: list[str], phrases: list[str]) -> dict[str, list[str]]:
    """เกณฑ์ที่เอาทักษะ (หรือตัวเลือกในกลุ่ม "A | B") ที่ตรงกับถ้อยคำเหล่านี้ออก — ใช้ตอน HR ถอนการยืนยัน
    แล้วเลือก "ลบออกจากเกณฑ์ด้วย" · ตัวเลือกอื่นในกลุ่มยังอยู่ กลุ่มที่เหลือตัวเลือกเดียวกลายเป็นทักษะเดี่ยว."""
    def keep(skills: list[str]) -> list[str]:
        out = []
        for s in skills or []:
            options = alternatives(s) or [s]
            left = [o for o in options if not any(_same_phrase(o, p) for p in phrases)]
            if len(left) == len(options):
                out.append(s)
            elif left:
                out.append(" | ".join(left))
        return out

    return {"required_skills": keep(required), "preferred_skills": keep(preferred)}


def biased_skill_message(found: list[dict[str, Any]]) -> str:
    """ข้อความเดียวกันทั้ง 409 ตอนบันทึกและคำเตือนตอนพรีวิว."""
    names = ", ".join(f'"{f["skill"]}"' for f in found)
    if all(f["phrase"] for f in found):
        how = 'ลบออกจากทักษะ หรือกด "จำเป็นกับงานนี้" ที่ถ้อยคำนั้นพร้อมเหตุผล แล้วบันทึกอีกครั้ง'
    else:
        how = "ลบออกจากทักษะก่อนบันทึก (ไม่มีถ้อยคำนี้ในประกาศให้ยืนยัน)"
    return f"ทักษะ {names} ตรงกับถ้อยคำที่อาจมีอคติ จะถูกนำไปคิดคะแนน — {how}"
