"""Node 1: JD Analyzer — แปลง JD ดิบเป็น JobRequirement (structured)."""
from app.agents.llm import structured_invoke
from app.agents.models import JobRequirement
from app.agents.state import HRSystemState

PROMPT = """คุณคือผู้เชี่ยวชาญ HR จงดึงข้อมูลสำคัญจากประกาศรับสมัครงานนี้ให้อยู่ในรูปแบบต่อไปนี้:
- job_title: ชื่อตำแหน่ง
- min_experience_years: จำนวนปีขั้นต่ำ
- required_skills: ทักษะที่ต้องมี (Must-have)
- preferred_skills: ทักษะที่มีก็ดี (Nice-to-have)
- education: ระดับการศึกษา

กติกาของ required_skills และ preferred_skills:
- ใส่ได้เฉพาะ "สิ่งที่ผู้สมัครทำเป็น" — เทคโนโลยี ภาษาโปรแกรม เครื่องมือ เฟรมเวิร์ก หรือวิธีการทำงาน
- ห้ามใส่ชื่อตำแหน่งหรือบทบาทของคนที่ต้องร่วมงานด้วย เช่น "data scientists", "product owners",
  "solution architects", "engineers" — พวกนี้คือเพื่อนร่วมงาน ไม่ใช่ทักษะ
- ใช้ชื่อที่เป็นทางการของเทคโนโลยีนั้น (เช่น "PostgreSQL" ไม่ใช่ "ฐานข้อมูล")

ประกาศรับสมัครงาน:
{raw_jd}"""


def analyze_jd(state: HRSystemState) -> dict:
    # รันแบบต่อผู้สมัคร: ถ้ามีผลวิเคราะห์ JD ส่งมาแล้ว ให้ข้าม (ไม่เรียก LLM ซ้ำ)
    if state.get("analyzed_jd"):
        return {}
    result = structured_invoke(PROMPT.format(raw_jd=state["raw_jd"]), JobRequirement)
    return {"analyzed_jd": result.model_dump()}
