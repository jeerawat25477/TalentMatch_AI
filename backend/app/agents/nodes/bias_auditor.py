"""Node 4: Bias Auditor — ตรวจอคติในผลประเมิน (ใช้ Pro เพื่อคุณภาพ)."""
from app.agents.llm import structured_invoke
from app.agents.models import BiasAudit
from app.agents.state import HRSystemState

PROMPT = """จงตรวจสอบผลการประเมินของผู้สมัครคนนี้ว่ามีการระบุข้อมูลอคติเกี่ยวกับ เพศ, อายุ,
เชื้อชาติ, ศาสนา หรือสถาบันการศึกษาหรือไม่ ถ้ามี ให้ตัดข้อมูลอคติออกแล้วประเมินทักษะอย่างเที่ยงตรง

ผลการประเมิน (gap analysis): {gaps}
ทักษะผู้สมัคร: {skills}
- is_biased: true ถ้าพบการใช้ปัจจัยอคติ
- audit_status: "flagged" ถ้าพบ, ไม่งั้น "passed"
- audit_log: สรุปสั้น ๆ ว่าตรวจพบอะไร/แก้ไขอะไร"""


def audit_bias(state: HRSystemState) -> dict:
    evaluation = dict(state["evaluations"][0])
    profile = state["parsed_resumes"][0]
    audit = structured_invoke(
        PROMPT.format(gaps=evaluation.get("gaps"), skills=profile.get("skills")),
        BiasAudit,
        complex=True,
    )
    evaluation["is_biased"] = audit.is_biased
    evaluation["audit_status"] = audit.audit_status
    evaluation["audit_log"] = audit.audit_log
    return {"evaluations": [evaluation]}
