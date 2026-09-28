"""Node 4: Bias Auditor — ตรวจอคติของประกาศงาน **ครั้งเดียวต่อตำแหน่ง** แล้วทุกผู้สมัครอ่านผลเดียวกัน.

สิ่งที่ตัวตรวจดูเป็นของตำแหน่งแทบทั้งหมด (ประกาศต้นฉบับ, required/preferred_skills, education,
ประสบการณ์ขั้นต่ำ) ส่วนของผู้สมัครมีแค่ผลเทียบทักษะ ซึ่งเป็นสูตรตายตัวที่ไม่รู้จักเพศหรืออายุอยู่แล้ว
เดิมเรียก LLM ทุกผู้สมัคร จึงเสีย 1 call ต่อคนกับคำตอบเดียวกัน และคำตอบยังต่างกันทุกรอบ
(ประกาศเดียวกันเคยได้คำอธิบายสามแบบ) ตอนนี้แบ่งเป็นสองจังหวะ:

1. ตอน HR กด "วิเคราะห์" ในหน้าสร้างตำแหน่ง — `audit_jd` เรียก LLM หนึ่งครั้ง แล้ว
   `build_jd_audit` รวมกับด่านกฎตายตัว (bias_rules.py) เก็บลง `jobs.jd_audit`
   HR เห็นคำเตือนในขั้นยืนยันเกณฑ์ **ก่อน**บันทึก แทนที่จะรู้หลังมีคนสมัครแล้ว
2. ต่อผู้สมัคร — `audit_bias` (โหนดในกราฟ) **ไม่เรียก LLM** อ่าน `state["jd_audit"]` ที่ worker
   โหลดมาจากตำแหน่ง ถ้าไม่มี (ตำแหน่งเก่าหรือ checkpoint เก่า) ใช้กฎอย่างเดียว ฟรี

โหนดยังอยู่ในกราฟ (รูปกราฟเปลี่ยน checkpoint เดิมใช้ไม่ได้) และลูป revise ยังทำงานเหมือนเดิม:
ถ้าผลตรวจของตำแหน่งระบุเกณฑ์ทักษะที่มีอคติ matcher ถอดแล้วคำนวณใหม่หนึ่งรอบ
"""
from typing import Any, Optional

from app.agents.bias_rules import categories, find_biased_phrases, merge_criteria
from app.agents.llm import structured_invoke_once
from app.agents.models import BiasAudit
from app.agents.state import HRSystemState

MAX_BIAS_REVISIONS = 1
_MAX_JD_CHARS = 4000  # ตัด JD ที่ยาวผิดปกติกันเปลือง token (JD ปกติสั้นกว่านี้มาก)

PROMPT = """จงตรวจสอบว่าประกาศรับสมัครงานนี้ และเกณฑ์ที่สกัดออกมาจากมัน มีการใช้ข้อมูลอคติ
เกี่ยวกับเรื่องต่อไปนี้หรือไม่: เพศ, อายุ, เชื้อชาติ/สัญชาติ/ภูมิลำเนา, ศาสนา, สถาบันการศึกษา,
สถานภาพสมรส (โสด/มีบุตร/ภาระครอบครัว), รูปลักษณ์ (ส่วนสูง/น้ำหนัก/หน้าตา/สีผิว),
ความพิการหรือสภาพร่างกายที่ไม่เกี่ยวกับงาน

ประกาศรับสมัครงาน (ต้นฉบับ):
{raw_jd}

เกณฑ์ที่สกัดออกมาแล้ว — required_skills: {required_skills}
preferred_skills: {preferred_skills}
education: {education} | ประสบการณ์ขั้นต่ำ: {min_experience_years} ปี

- is_biased: true ถ้าพบการใช้ปัจจัยอคติ
- audit_status: "flagged" ถ้าพบ, ไม่งั้น "passed"
- audit_log: สรุปสั้น ๆ ว่าตรวจพบอะไร (ดูกติกาการเขียนข้างล่าง)
- biased_required_skills / biased_preferred_skills: เฉพาะรายการที่อยู่ใน required_skills /
  preferred_skills ข้างบน "ตรงตัวอักษร" และเป็นเกณฑ์อคติ — ระบบจะถอดออกแล้วคำนวณคะแนนใหม่
  ถ้าไม่มีรายการไหนเข้าข่าย ให้คืน list ว่าง (ห้ามเดาชื่อที่ไม่ได้อยู่ในลิสต์)
- biased_jd_criteria: เกณฑ์อคติที่พบใน "ประกาศต้นฉบับ" หรือช่อง education/ประสบการณ์ ซึ่งไม่ใช่
  ทักษะ (เช่น "เพศชาย", "อายุไม่เกิน 30", "จบจากมหาวิทยาลัยชั้นนำ") — ถอดออกจากคะแนนไม่ได้
  เพราะไม่ได้ถูกใช้คิดคะแนนอยู่แล้ว แต่ต้องเตือน HR ให้ไปแก้ประกาศ
  ยกข้อความจากประกาศจริงเท่านั้น ห้ามแต่งหรือสรุปความเอง

กติกาการเขียน audit_log:
- เกณฑ์อคติที่อยู่ในประกาศแต่ "ไม่อยู่" ใน required_skills / preferred_skills ให้เขียนว่า
  "ไม่ได้ถูกใช้คิดคะแนน" **ห้ามเขียนว่า "ถอดออกแล้ว"** เพราะมันไม่เคยถูกใส่เข้าไปตั้งแต่แรก
- ถ้าไม่พบอะไร ให้บอกสั้น ๆ ว่าไม่พบ ห้ามปั้นปัญหาขึ้นมา"""


def audit_jd(
    raw_jd: str,
    required_skills: list[str],
    preferred_skills: list[str],
    education: str = "",
    min_experience_years: int = 0,
) -> BiasAudit:
    """ให้ LLM ตรวจประกาศหนึ่งครั้ง — เรียกจาก /jobs/analyze ตอน HR นั่งรออยู่.

    ใช้ structured_invoke_once (ไม่ retry) เหตุผลเดียวกับ jd_reviewer: ถ้าโควตาหมด การ retry
    หน่วงเป็นนาทีแล้วก็ล้มอยู่ดี ผู้เรียกถอยไปใช้กฎอย่างเดียวได้ทันที
    """
    return structured_invoke_once(
        PROMPT.format(
            # ส่ง JD ต้นฉบับ เพราะ jd_analyzer กรองเกณฑ์อย่าง "เพศชาย/อายุไม่เกิน 30" ทิ้งตั้งแต่ต้น
            # ถ้าดูแต่ผลที่สกัดแล้วจะมองไม่เห็นอคติที่อยู่ในประกาศเลย
            raw_jd=(raw_jd or "")[:_MAX_JD_CHARS],
            required_skills=required_skills or [],
            preferred_skills=preferred_skills or [],
            education=education or "-",
            min_experience_years=min_experience_years or 0,
        ),
        BiasAudit,
        complex=True,
    )


def _clean(items: list[str] | None) -> list[str]:
    return [s.strip() for s in (items or []) if s and s.strip()]


def build_jd_audit(llm: Optional[BiasAudit], raw_jd: str) -> dict[str, Any]:
    """รวมผลของ LLM (ถ้ามี) กับด่านกฎตายตัว เป็นผลตรวจของตำแหน่งที่พร้อมเก็บและแสดง — ฟังก์ชันบริสุทธิ์.

    `llm=None` = กฎอย่างเดียว (AI อ่านไม่สำเร็จ, HR กรอกเกณฑ์เอง, ตำแหน่งเก่า) ไม่เสีย call
    `log` คือข้อความสุดท้ายรวมบรรทัด ⚠ แล้ว — ผู้สมัครทุกคนในตำแหน่งได้ข้อความนี้ตรงตัว

    กฎอ่านประกาศเต็ม ไม่ตัดที่ _MAX_JD_CHARS เพราะไม่กิน token และถ้ากฎเจอแต่ LLM ตอบ passed
    ต้องแทน log ด้วย ไม่งั้นหน้าเว็บจะได้ข้อความขัดกันเอง "ไม่พบอคติ" ตามด้วยบรรทัด ⚠
    """
    hits = find_biased_phrases(raw_jd or "")
    flagged = bool(llm and llm.audit_status == "flagged")
    if llm and (flagged or not hits):
        log = llm.audit_log
    elif hits:
        log = (
            f"พบถ้อยคำที่อาจมีอคติในประกาศรับสมัครงาน ({', '.join(categories(hits))}) "
            "— ไม่ได้ถูกใช้คิดคะแนน แต่ควรแก้ประกาศ"
        )
    else:
        log = "ไม่พบถ้อยคำที่เข้าข่ายอคติในประกาศ (ตรวจด้วยกฎตายตัว)"

    jd_criteria = merge_criteria(llm.biased_jd_criteria if llm else [], hits, raw_jd or "")
    if jd_criteria:
        log = (
            f"{log}\n"
            f"⚠ เกณฑ์ใน JD ที่อาจมีอคติ (ไม่ได้ถูกใช้คิดคะแนน — ควรแก้ประกาศ): "
            f"{', '.join(jd_criteria)}"
        ).strip()

    return {
        "status": "flagged" if (flagged or hits) else "passed",
        "log": log,
        "jd_criteria": jd_criteria,
        "biased_required_skills": _clean(llm.biased_required_skills) if llm else [],
        "biased_preferred_skills": _clean(llm.biased_preferred_skills) if llm else [],
        "llm_checked": llm is not None,
    }


def audit_bias(state: HRSystemState) -> dict:
    """โหนดในกราฟ — อ่านผลตรวจของตำแหน่ง ไม่เรียก LLM."""
    evaluation = dict(state["evaluations"][0])
    jd_audit = state.get("jd_audit") or build_jd_audit(None, state.get("raw_jd") or "")

    cid = evaluation["candidate_id"]
    revision_count = dict(state.get("bias_revision_count") or {})
    revision_pending = dict(state.get("bias_revision_pending") or {})
    exclusions = dict(state.get("bias_exclusions") or {})

    flagged = jd_audit.get("status") == "flagged"
    evaluation["is_biased"] = flagged
    evaluation["audit_status"] = "flagged" if flagged else "passed"
    evaluation["audit_log"] = jd_audit.get("log") or ""

    required_exclusions = _clean(jd_audit.get("biased_required_skills"))
    preferred_exclusions = _clean(jd_audit.get("biased_preferred_skills"))
    can_revise = (
        flagged
        and revision_count.get(cid, 0) < MAX_BIAS_REVISIONS
        and (required_exclusions or preferred_exclusions)
    )
    if can_revise:
        revision_count[cid] = revision_count.get(cid, 0) + 1
        revision_pending[cid] = True
        exclusions[cid] = {
            "required_skills": required_exclusions,
            "preferred_skills": preferred_exclusions,
            "reason": evaluation["audit_log"],
        }
        # ไม่ต้องเขียน evaluation["bias_revision"] ที่นี่ — ในรอบ revise matcher สร้าง
        # evaluation dict ใหม่อยู่แล้ว จึงให้ matcher เป็นคนบันทึก (มันรู้คะแนนก่อน/หลัง)
        # แล้ว auditor รอบสองคัดลอกต่อผ่าน dict(state["evaluations"][0]) ไปถึง DB
        # และห้ามต่อข้อความลง audit_log เพราะ auditor รอบสองเขียนทับทั้งช่องอยู่ดี
    else:
        revision_pending[cid] = False

    return {
        "evaluations": [evaluation],
        "bias_revision_count": revision_count,
        "bias_revision_pending": revision_pending,
        "bias_exclusions": exclusions,
    }
