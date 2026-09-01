"""Node 4: Bias Auditor — ตรวจอคติในผลประเมิน (ใช้ Pro เพื่อคุณภาพ)."""
from app.agents.llm import structured_invoke
from app.agents.models import BiasAudit
from app.agents.state import HRSystemState

MAX_BIAS_REVISIONS = 1
_MAX_JD_CHARS = 4000  # ตัด JD ที่ยาวผิดปกติกันเปลือง token (JD ปกติสั้นกว่านี้มาก)

PROMPT = """จงตรวจสอบว่าการประเมินผู้สมัครคนนี้ และตัวประกาศรับสมัครงานเอง มีการใช้ข้อมูลอคติ
เกี่ยวกับ เพศ, อายุ, เชื้อชาติ, ศาสนา หรือสถาบันการศึกษาหรือไม่

ประกาศรับสมัครงาน (ต้นฉบับ):
{raw_jd}

เกณฑ์ที่สกัดออกมาแล้ว — JD required_skills: {required_skills}
JD preferred_skills: {preferred_skills}
JD education: {education} | ประสบการณ์ขั้นต่ำ: {min_experience_years} ปี
ผลการประเมิน (gap analysis): {gaps}
ทักษะผู้สมัคร: {skills}

- is_biased: true ถ้าพบการใช้ปัจจัยอคติ
- audit_status: "flagged" ถ้าพบ, ไม่งั้น "passed"
- audit_log: สรุปสั้น ๆ ว่าตรวจพบอะไร/แก้ไขอะไร
- biased_required_skills / biased_preferred_skills: เฉพาะรายการที่อยู่ใน required_skills /
  preferred_skills ข้างบน "ตรงตัวอักษร" และเป็นเกณฑ์อคติ — matcher จะถอดออกแล้วคำนวณคะแนนใหม่
  ถ้าไม่มีรายการไหนเข้าข่าย ให้คืน list ว่าง (ห้ามเดาชื่อที่ไม่ได้อยู่ในลิสต์)
- biased_jd_criteria: เกณฑ์อคติที่พบใน "ประกาศต้นฉบับ" หรือช่อง education/ประสบการณ์ ซึ่งไม่ใช่
  ทักษะ (เช่น "เพศชาย", "อายุไม่เกิน 30", "จบจากมหาวิทยาลัยชั้นนำ") — ถอดออกจากคะแนนไม่ได้
  เพราะไม่ได้ถูกใช้คิดคะแนนอยู่แล้ว แต่ต้องเตือน HR ให้ไปแก้ประกาศ"""


def audit_bias(state: HRSystemState) -> dict:
    evaluation = dict(state["evaluations"][0])
    profile = state["parsed_resumes"][0]
    jd = state["analyzed_jd"] or {}
    audit = structured_invoke(
        PROMPT.format(
            # ส่ง JD ต้นฉบับด้วย เพราะ jd_analyzer กรองเกณฑ์อย่าง "เพศชาย/อายุไม่เกิน 30" ทิ้ง
            # ตั้งแต่ node แรก (prompt ของมันรับเฉพาะ "สิ่งที่ผู้สมัครทำเป็น") — ถ้าดูแต่ผลที่สกัดแล้ว
            # auditor จะมองไม่เห็นอคติที่อยู่ในประกาศเลย. ตัดความยาวกันเปลือง token
            raw_jd=(state.get("raw_jd") or "")[:_MAX_JD_CHARS],
            required_skills=jd.get("required_skills") or [],
            preferred_skills=jd.get("preferred_skills") or [],
            education=jd.get("education") or "-",
            min_experience_years=jd.get("min_experience_years", 0),
            gaps=evaluation.get("gaps"),
            skills=profile.get("skills"),
        ),
        BiasAudit,
        complex=True,
    )
    cid = evaluation["candidate_id"]
    revision_count = dict(state.get("bias_revision_count") or {})
    revision_pending = dict(state.get("bias_revision_pending") or {})
    exclusions = dict(state.get("bias_exclusions") or {})

    evaluation["is_biased"] = audit.is_biased
    evaluation["audit_status"] = audit.audit_status
    evaluation["audit_log"] = audit.audit_log

    # เกณฑ์อคติที่อยู่ใน JD แต่ไม่ใช่ทักษะ (เพศ/อายุ/สถาบัน) ถอดออกจากคะแนนไม่ได้ เพราะมันไม่เคย
    # ถูกใช้คิดคะแนนอยู่แล้ว — สิ่งที่ทำได้คือเตือน HR ให้ไปแก้ประกาศ จึงต่อท้าย audit_log
    # (ปลอดภัยที่จะต่อตรงนี้: คำนวณใหม่ทุกรอบจากผล audit ของรอบนั้น ไม่ใช่ข้อความสะสม)
    jd_criteria = [c.strip() for c in audit.biased_jd_criteria if c and c.strip()]
    if jd_criteria:
        evaluation["audit_log"] = (
            f"{audit.audit_log}\n"
            f"⚠ เกณฑ์ใน JD ที่อาจมีอคติ (ไม่ได้ถูกใช้คิดคะแนน — ควรแก้ประกาศ): "
            f"{', '.join(jd_criteria)}"
        ).strip()

    required_exclusions = [s for s in audit.biased_required_skills if s and s.strip()]
    preferred_exclusions = [s for s in audit.biased_preferred_skills if s and s.strip()]
    can_revise = (
        audit.audit_status == "flagged"
        and revision_count.get(cid, 0) < MAX_BIAS_REVISIONS
        and (required_exclusions or preferred_exclusions)
    )
    if can_revise:
        next_count = revision_count.get(cid, 0) + 1
        revision_count[cid] = next_count
        revision_pending[cid] = True
        exclusions[cid] = {
            "required_skills": required_exclusions,
            "preferred_skills": preferred_exclusions,
            "reason": audit.audit_log,
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
