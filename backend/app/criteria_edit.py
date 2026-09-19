"""HR แก้รายการทักษะของตำแหน่งงาน แล้วคำนวณคะแนนคนเดิมใหม่ — ไม่เรียก LLM เลย.

ที่มา (memory-bank/06_scoring_criteria.md): สูตรคะแนนไม่ผิด แต่ข้อมูลเข้าสูตรผิด
jd_analyzer ดึงทักษะจาก JD ครั้งเดียวตอนสร้างตำแหน่ง แล้วไม่มีใครตรวจ ตัวเลือกแบบ
"A, B, or C" จึงกลายเป็นข้อบังคับทุกตัว หน้าที่งานกลายเป็นทักษะ คนที่ตรงคุณสมบัติครบ
อาจได้ 28 แล้วถูกปฏิเสธอัตโนมัติ

กติกาที่ต้องรักษา:
- **ประเมินผ่าน matcher.evaluate_skills ตัวเดียวกับกราฟ** ไม่เทียบทักษะหรือคำนวณเอง
  ไม่งั้นคนเดิมที่ถูกคำนวณใหม่กับคนใหม่ที่กราฟประเมินภายใต้เกณฑ์เดียวกันจะได้คะแนนต่างกัน
- **ไม่ทำอะไรเองนอกจากคะแนน** ไม่เดินกราฟใหม่ ไม่แตะร่างอีเมล คำถามสัมภาษณ์ คำตัดสินของ HR
  หรือขั้นบนกระดาน · คนที่แบนด์เปลี่ยนขึ้นป้ายให้ HR ตรวจเอง (ผู้ใช้ตัดสิน 2026-09-18)
- ส่วนที่เป็นกฎล้วนเป็นฟังก์ชันบริสุทธิ์ ทดสอบได้โดยไม่ต้องมี DB
"""
import re
from datetime import datetime
from typing import Optional

from psycopg.types.json import Json

from app.agents.bands import band
from app.agents.nodes.matcher import evaluate_skills
from app.agents.skills import GROUP_SEP, alternatives, canonical, is_skill

# ทักษะที่ต้องมีเกินเท่านี้เป็นสัญญาณว่าเกณฑ์พอง — AI Engineer ที่เจอปัญหามี 19 และ 32 ข้อ
# ส่วนตำแหน่งที่ดึงถูกมี 3-7 ข้อ · เป็นคำเตือน ไม่ใช่ข้อห้าม
BLOATED_REQUIRED = 15


def normalize_criteria(required: list[str], preferred: list[str]) -> dict:
    """ทำความสะอาดรายการที่ HR ส่งมา — ฟังก์ชันบริสุทธิ์.

    - ตัดช่องว่างหัวท้ายและช่องที่ว่าง
    - ตัดซ้ำด้วย skills.canonical ทั้งภายในฝั่งเดียวกันและข้ามฝั่ง ("Node.js" กับ "NodeJs"
      คือทักษะเดียวกัน) · ถ้าอยู่ทั้งสองฝั่ง ฝั่งที่ต้องมีชนะ
    - คำที่ is_skill() ไม่รับ (เช่นชื่อบทบาท "product owners") ถูกคัดออกและ **คืนมาใน dropped**
      ให้ HR เห็น — matcher กรองคำพวกนี้ทิ้งตอนคำนวณอยู่แล้ว ถ้าปล่อยไว้เงียบ ๆ HR จะเห็น
      ชิปที่ไม่ได้ถูกนับจริง
    """
    seen: set[str] = set()
    dropped: list[str] = []

    def clean(items: list[str]) -> list[str]:
        out: list[str] = []
        for raw in items:
            s = _clean_group(raw or "", dropped)
            if not s:
                continue
            # กลุ่ม "A | B" กับ "B | A" คือเกณฑ์เดียวกัน — เทียบซ้ำแบบไม่สนลำดับตัวเลือก
            key = GROUP_SEP.join(sorted(canonical(a) for a in alternatives(s)))
            if key in seen:
                continue
            seen.add(key)
            if not is_skill(s):
                dropped.append(s)
                continue
            out.append(s)
        return out

    req = clean(required)  # ฝั่งที่ต้องมีก่อน จึงชนะเมื่อซ้ำข้ามฝั่ง
    pref = clean(preferred)
    return {"required_skills": req, "preferred_skills": pref, "dropped": dropped}


def _clean_group(raw: str, dropped: list[str]) -> str:
    """จัดรูปกลุ่ม "ข้อใดข้อหนึ่ง": ตัดช่องว่าง ตัวเลือกซ้ำ และตัวเลือกที่ไม่ใช่ทักษะ (แจ้งใน dropped)
    เหลือตัวเดียว → เป็นทักษะธรรมดา · ทักษะธรรมดาคืนตามเดิม (ตัดช่องว่างหัวท้าย)."""
    alts = alternatives(raw)
    if len(alts) <= 1:
        return alts[0] if alts else ""
    keep: list[str] = []
    keys: set[str] = set()
    for a in alts:
        k = canonical(a)
        if not k or k in keys:
            continue
        keys.add(k)
        if not is_skill(a):
            dropped.append(a)
            continue
        keep.append(a)
    return f" {GROUP_SEP} ".join(keep)


def criteria_warnings(required: list[str], preferred: list[str]) -> list[str]:
    """คำเตือนที่ HR ควรเห็นก่อนบันทึก — ฟังก์ชันบริสุทธิ์ (ตัวเลขทุกตัวมาจากกติกาใน matcher)."""
    warnings: list[str] = []
    if not required and not preferred:
        warnings.append(
            "ไม่มีทักษะเลย — ทุกคนจะได้คะแนนกลางและรอคนตัดสิน ระบบจะไม่เทียบทักษะให้"
        )
    elif not required:
        warnings.append(
            "มีแค่ทักษะที่อยากได้ — ฝั่งนี้จะคิดเต็ม 100 คะแนน คนที่ไม่มีทักษะเสริมเลย"
            "จะได้ 0 แล้วถูกปฏิเสธอัตโนมัติ ทั้งที่ประกาศบอกว่าไม่มีก็ได้"
        )
    if len(required) > BLOATED_REQUIRED:
        warnings.append(
            f"ทักษะที่ต้องมีมี {len(required)} ข้อ — ทุกข้อนับเป็นข้อบังคับ ถ้าบางข้อเป็น"
            "ตัวเลือกแบบ \"หรือ\" หรือเป็นหน้าที่งาน คะแนนของทุกคนจะต่ำเกินจริง"
        )
    # เช็กทีละตัวเลือก — กลุ่มยาว ๆ อย่าง "PyTorch | TensorFlow | Hugging Face" ไม่ใช่ประโยค
    phrases = [a for s in required for a in alternatives(s) if looks_like_phrase(a)]
    if phrases:
        shown = ", ".join(f'"{s}"' for s in phrases[:3])
        more = f" และอีก {len(phrases) - 3} ข้อ" if len(phrases) > 3 else ""
        warnings.append(
            f"ทักษะบางข้อดูเป็นประโยค อาจไม่ตรงกับเรซูเม่ใครเลย ควรแก้ให้สั้น: {shown}{more}"
        )
    return warnings


_THAI = re.compile(r"[฀-๿]")
PHRASE_MAX_WORDS = 4
PHRASE_MAX_CHARS = 40


def looks_like_phrase(skill: str) -> bool:
    """ชื่อทักษะที่ดูเป็นประโยคมากกว่าชื่อ — ฟังก์ชันบริสุทธิ์.

    AI เคยใส่ "ใช้ AI ในการเขียนโปรแกรม" เป็นข้อบังคับ (Software Engineer 31854880) ไม่มีใครเขียน
    แบบนี้ในเรซูเม่ ทุกคนจึงขาดข้อนี้เท่ากันหมด · ภาษาไทยไม่เว้นวรรคระหว่างคำ ชื่อไทยที่มีช่องว่าง
    จึงมักเป็นวลี ("ความรู้ด้าน AI") ส่วนชื่ออังกฤษดูจากจำนวนคำและความยาว
    ใช้เตือน HR เท่านั้น — ไม่แก้ชื่อหรือคะแนนให้เอง
    """
    s = skill.strip()
    if _THAI.search(s) and " " in s:
        return True
    return len(s.split()) > PHRASE_MAX_WORDS or len(s) > PHRASE_MAX_CHARS


def needs_recheck(
    rescored_at: Optional[datetime],
    rescored_from: Optional[int],
    fit_score: Optional[int],
    hr_decided_at: Optional[datetime],
) -> bool:
    """ควรขึ้นป้าย "เกณฑ์เปลี่ยน ตรวจอีกครั้ง" ไหม — ฟังก์ชันบริสุทธิ์.

    True เมื่อคะแนนถูกคำนวณใหม่จนแบนด์เปลี่ยนจากตอนที่กราฟ/HR ตัดสินไว้ และ HR ยังไม่ได้
    ตัดสินอีกครั้งหลังจากนั้น · แบนด์เดิม (เช่น 55 → 62 ยังรอ HR) ไม่ต้องขึ้นป้าย เพราะ
    เส้นทางที่กราฟเดินไปแล้วยังถูกอยู่
    """
    if rescored_at is None or rescored_from is None or fit_score is None:
        return False
    if band(rescored_from) == band(fit_score):
        return False
    return hr_decided_at is None or hr_decided_at < rescored_at


_ROWS = """
    SELECT e.candidate_id, c.full_name, c.parsed_resume, c.raw_resume_text,
           e.fit_score, e.bias_revision, e.rescored_from, e.rescored_at,
           e.email_sent_at, hd.decision AS hr_decision, hd.updated_at AS hr_decided_at
      FROM evaluations e
      JOIN candidates c ON c.id = e.candidate_id
      LEFT JOIN hr_decisions hd ON hd.candidate_id = c.id
     WHERE c.job_id = %s AND c.parsed_resume IS NOT NULL
     ORDER BY e.fit_score DESC, c.full_name
"""


def _exclusions(bias_revision: Optional[dict]) -> dict:
    """เกณฑ์ที่ลูปตรวจอคติเคยตัดไว้ — ต้องตัดต่อไปแม้ HR จะแก้เกณฑ์ใหม่."""
    br = bias_revision or {}
    return {
        "required_skills": br.get("excluded_required") or [],
        "preferred_skills": br.get("excluded_preferred") or [],
    }


def rescore_job(conn, job_id: str, required: list[str], preferred: list[str], apply: bool) -> list[dict]:
    """คำนวณคะแนนผู้สมัครทุกคนของตำแหน่งนี้ใหม่ตามเกณฑ์ที่ให้มา.

    apply=False (พรีวิว) ไม่เขียนอะไรเลย · apply=True เขียนเฉพาะผลประเมิน
    (fit_score, gap_analysis, score_explanation, skill_evidence, confidence) และร่องรอย
    rescored_from/rescored_at ของคนที่คะแนนเปลี่ยน — ผู้เรียกเป็นคน commit

    ผู้สมัครที่ยังไม่มี parsed_resume (ยังวิเคราะห์ไม่เสร็จ) ถูกข้าม กราฟจะอ่านเกณฑ์ใหม่จาก
    jobs.parsed_criteria เองตอนประมวลผล
    """
    rows = conn.execute(_ROWS, (job_id,)).fetchall()
    impact: list[dict] = []
    for r in rows:
        result = evaluate_skills(
            required,
            preferred,
            r["parsed_resume"] or {},
            r["raw_resume_text"] or "",
            _exclusions(r["bias_revision"]),
        )
        old, new = r["fit_score"], result["fit_score"]
        impact.append({
            "candidate_id": r["candidate_id"],
            "full_name": r["full_name"],
            "old_score": old,
            "new_score": new,
            "old_band": band(old),
            "new_band": band(new),
            "hr_decision": r["hr_decision"],
            "email_sent": r["email_sent_at"] is not None,
        })
        if not apply:
            continue
        # rescored_from เก็บคะแนน "ตอนที่กราฟหรือ HR ตัดสินไว้" — แก้เกณฑ์หลายรอบต้องไม่ทับ
        # ค่าเดิม ไม่งั้นป้ายจะเทียบกับคะแนนรอบก่อนหน้าแทนคะแนนที่มีคนตัดสินจริง
        # เว้นแต่ HR ตัดสินใหม่แล้วหลังคำนวณครั้งก่อน ฐานจึงเป็นคะแนนปัจจุบัน
        decided_since = (
            r["rescored_at"] is not None
            and r["hr_decided_at"] is not None
            and r["hr_decided_at"] >= r["rescored_at"]
        )
        base = old if r["rescored_from"] is None or decided_since else r["rescored_from"]
        conn.execute(
            """
            UPDATE evaluations
               SET fit_score = %(new)s,
                   gap_analysis = %(gaps)s,
                   score_explanation = %(explanation)s,
                   skill_evidence = %(evidence)s,
                   confidence = %(confidence)s,
                   rescored_from = CASE WHEN %(changed)s THEN %(base)s ELSE rescored_from END,
                   rescored_at = CASE WHEN %(changed)s THEN now() ELSE rescored_at END
             WHERE candidate_id = %(cid)s
            """,
            {
                "new": new,
                "gaps": Json(result["gaps"]),
                "explanation": result["score_explanation"],
                "evidence": Json(result["skill_evidence"]) if result["skill_evidence"] else None,
                "confidence": result["confidence"],
                "changed": new != old,
                "base": base,
                "cid": r["candidate_id"],
            },
        )
    return impact
