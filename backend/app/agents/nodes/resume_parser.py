"""Node 2: Resume Parser — แปลงข้อความ resume เป็น ResumeProfile (ฟอร์แมตเดียวกับ JD).

ถาม LLM สองครั้งต่อเรซูเม่หนึ่งฉบับ: ครั้งแรกสกัดโปรไฟล์ ครั้งที่สองหาหลักฐานของทักษะ
**ห้ามรวมเป็น prompt เดียว** — วัดกับเรซูเม่จริงแล้วพบว่าการเพิ่มงาน "หาหลักฐาน" เข้าไป
ทำให้ gemini-2.5-flash-lite แกะฟิลด์เดิมแย่ลง (ดูคอมเมนต์ใน models.SkillEvidence)
"""
import logging

from app.agents.evidence import MAX_EVIDENCE_CHARS, filter_evidence
from app.agents.llm import structured_invoke
from app.agents.models import ResumeProfile, SkillEvidence
from app.agents.state import HRSystemState

log = logging.getLogger(__name__)

PROMPT = """คุณคือผู้เชี่ยวชาญ HR จงสกัดข้อมูลจากเรซูเม่นี้ให้อยู่ในรูปแบบ:
- full_name: ชื่อ-นามสกุล
- email: อีเมล (ถ้ามี)
- total_experience_years: ปีประสบการณ์รวมโดยประมาณ
- skills: รายการทักษะทั้งหมด
- education: วุฒิการศึกษาสูงสุด

เนื้อหาเรซูเม่:
{content}"""

EVIDENCE_PROMPT = """จากเรซูเม่ข้างล่าง จงหาข้อความที่เป็นหลักฐานของแต่ละทักษะต่อไปนี้:
{skills}

กติกา:
1. คีย์ต้องเป็นชื่อทักษะที่สะกดตรงกับรายการข้างบนเป๊ะ
2. ค่าต้องเป็นข้อความที่ **คัดลอกจากเรซูเม่มาตรง ๆ** ห้ามแต่งขึ้นเอง ห้ามสรุปความ ห้ามแปล
3. ยกมาสั้น ๆ ประมาณ 1 ประโยค ไม่เกิน {max_chars} ตัวอักษร
   เลือกประโยคที่แสดง "การใช้งานจริง" มากกว่าบรรทัดที่เป็นรายการทักษะเฉย ๆ
4. ทักษะที่หาข้อความอ้างอิงไม่เจอ ให้ข้ามไป ไม่ต้องใส่ — ดีกว่าเดา

เนื้อหาเรซูเม่:
{content}"""


def _extract_evidence(skills: list[str], content: str) -> dict[str, str]:
    """หาหลักฐานของทักษะ แล้วตรวจกับเรซูเม่จริงก่อนคืน.

    หลักฐานเป็นของเสริม ไม่ใช่ของจำเป็น — ถ้า call นี้ล้ม (โควตาหมด/คีย์พัง) ต้องปล่อยผ่าน
    ให้กราฟเดินต่อ ไม่ใช่ทำให้ทั้งการประเมินล้มเพราะของประดับ
    """
    if not skills:
        return {}
    try:
        result = structured_invoke(
            EVIDENCE_PROMPT.format(
                skills="\n".join(f"- {s}" for s in skills),
                content=content,
                max_chars=MAX_EVIDENCE_CHARS,
            ),
            SkillEvidence,
        )
    except Exception as exc:  # noqa: BLE001 — ไม่มีหลักฐานยังใช้งานได้ ไม่มีคะแนนสิใช้ไม่ได้
        log.warning("หาหลักฐานทักษะไม่สำเร็จ ข้ามไป: %s", exc)
        return {}

    # ด่านกันมโน: ตรวจกับเรซูเม่จริงก่อนเข้า state — หลักฐานที่ยืนยันไม่ได้ต้องไม่มีวัน
    # ไปถึง DB หรือหน้าเว็บ เพราะ HR จะเชื่อโดยไม่กลับไปเปิดไฟล์
    return filter_evidence(result.evidence or {}, skills, content)


def parse_resumes(state: HRSystemState) -> dict:
    parsed: list[dict] = []
    for raw in state["raw_resumes"]:
        content = raw["content"]
        profile = structured_invoke(PROMPT.format(content=content), ResumeProfile)
        item = profile.model_dump()
        item["candidate_id"] = raw["candidate_id"]  # คงตัวระบุไว้ตลอดสาย
        item["skill_evidence"] = _extract_evidence(item.get("skills") or [], content)
        parsed.append(item)
    return {"parsed_resumes": parsed}
