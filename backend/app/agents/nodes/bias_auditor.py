"""Node 4: Bias Auditor — ตรวจอคติในผลประเมิน (ใช้ Pro เพื่อคุณภาพ)."""
from app.agents.llm import structured_invoke
from app.agents.models import BiasAudit
from app.agents.state import HRSystemState

MAX_BIAS_REVISIONS = 1

PROMPT = """จงตรวจสอบผลการประเมินของผู้สมัครคนนี้ว่ามีการระบุข้อมูลอคติเกี่ยวกับ เพศ, อายุ,
เชื้อชาติ, ศาสนา หรือสถาบันการศึกษาหรือไม่ ถ้ามี ให้ตัดข้อมูลอคติออกแล้วประเมินทักษะอย่างเที่ยงตรง

JD required_skills: {required_skills}
JD preferred_skills: {preferred_skills}
ผลการประเมิน (gap analysis): {gaps}
ทักษะผู้สมัคร: {skills}
- is_biased: true ถ้าพบการใช้ปัจจัยอคติ
- audit_status: "flagged" ถ้าพบ, ไม่งั้น "passed"
- audit_log: สรุปสั้น ๆ ว่าตรวจพบอะไร/แก้ไขอะไร
- biased_required_skills: รายการ required_skills จาก JD ที่ควรถอดออกก่อนให้ matcher คำนวณใหม่
- biased_preferred_skills: รายการ preferred_skills จาก JD ที่ควรถอดออกก่อนให้ matcher คำนวณใหม่

ถ้า flag เพราะข้อความทั่วไปแต่ไม่มี skill criterion ใน JD ที่ควรถอด ให้คืนรายการ biased_* เป็น list ว่าง"""


def audit_bias(state: HRSystemState) -> dict:
    evaluation = dict(state["evaluations"][0])
    profile = state["parsed_resumes"][0]
    jd = state["analyzed_jd"] or {}
    audit = structured_invoke(
        PROMPT.format(
            required_skills=jd.get("required_skills") or [],
            preferred_skills=jd.get("preferred_skills") or [],
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
