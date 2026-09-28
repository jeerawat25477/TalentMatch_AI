"""การยืนยันของ HR ว่าถ้อยคำที่ตัวตรวจอคติเตือน "จำเป็นกับงานนี้จริง".

บางงานเพศหรือสัญชาติเป็นคุณสมบัติที่จำเป็นจริง (เจ้าหน้าที่ตรวจค้นตัวผู้หญิง, อาชีพที่กฎหมาย
สงวนให้คนไทย) ถ้าไม่มีทางยืนยัน ⚠ จะขึ้นในหน้าผู้สมัครทุกคนตลอดไป เตือนซ้ำเรื่องที่ตัดสินแล้ว
นานไปคนจะเลิกอ่านคำเตือนทั้งหมด การยืนยันจึงต้อง

- **ทีละถ้อยคำ** — "เพศหญิง" จำเป็นไม่ได้แปลว่า "อายุไม่เกิน 30" ในประกาศเดียวกันจำเป็นด้วย
- **มีเหตุผล** อย่างน้อย MIN_REASON_CHARS ตัวอักษร กันการกดผ่านด้วย "ok"
- **รู้ว่าใคร เมื่อไร** — ชื่อมาจาก token ที่ล็อกอิน ไม่ใช่ค่าที่หน้าเว็บส่งมา
- **ไม่แตะคะแนน** — ถ้อยคำพวกนี้ไม่เคยอยู่ในคะแนนอยู่แล้ว การยืนยันเปลี่ยนแค่สิ่งที่ HR เห็น

ฟังก์ชันบริสุทธิ์ทั้งไฟล์ ทดสอบได้โดยไม่ต่อ DB
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

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


def bias_view(jd_audit: dict[str, Any] | None, acks: list[dict[str, Any]] | None) -> dict[str, Any] | None:
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
    acknowledged = [by_phrase[c] for c in criteria if c in by_phrase]
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
