"""Node 2: Resume Parser — แปลงข้อความ resume เป็น ResumeProfile (ฟอร์แมตเดียวกับ JD)."""
from app.agents.llm import structured_invoke
from app.agents.models import ResumeProfile
from app.agents.state import HRSystemState

PROMPT = """คุณคือผู้เชี่ยวชาญ HR จงสกัดข้อมูลจากเรซูเม่นี้ให้อยู่ในรูปแบบ:
- full_name: ชื่อ-นามสกุล
- email: อีเมล (ถ้ามี)
- total_experience_years: ปีประสบการณ์รวมโดยประมาณ
- skills: รายการทักษะทั้งหมด
- education: วุฒิการศึกษาสูงสุด

เนื้อหาเรซูเม่:
{content}"""


def parse_resumes(state: HRSystemState) -> dict:
    parsed: list[dict] = []
    for raw in state["raw_resumes"]:
        profile = structured_invoke(PROMPT.format(content=raw["content"]), ResumeProfile)
        item = profile.model_dump()
        item["candidate_id"] = raw["candidate_id"]  # คงตัวระบุไว้ตลอดสาย
        parsed.append(item)
    return {"parsed_resumes": parsed}
