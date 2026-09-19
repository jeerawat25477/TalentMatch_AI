"""Node 1: JD Analyzer — แปลง JD ดิบเป็น JobRequirement (structured).

ทำสองจังหวะใน LLM call เดียว:
1. LLM ติดป้ายทุกคำที่อาจเป็นทักษะ (JDExtraction) — ตอบคำถามแคบ ๆ ต่อคำ ไม่ตัดสินฝั่ง
2. `to_requirement` (โค้ด บริสุทธิ์) จัดฝั่ง required/preferred จากป้าย

ทำไมไม่ให้ LLM ตัดสินฝั่งเอง: `JobRequirement` เป็นรายการแบนที่ทุกข้อบังคับครบ (AND) และ
gemini-2.5-flash-lite ทำตามกติกายาว ๆ ได้ไม่ครบ (วัดแล้ว 2026-09-19 — memory-bank/06)
กติกาที่ย้ายมาอยู่ในโค้ดจึงเทสได้และไม่ขึ้นกับว่าโมเดลจำได้หรือไม่
ข้อจำกัดที่ยังอยู่: ตัวเลือก "A หรือ B" ไปฝั่ง preferred ทั้งหมด ข้อบังคับ "ต้องมีสักตัว" จึงหายไป
ทางแก้ที่ถูกคือกลุ่ม any-of (ทางแก้ข้อ 3) ซึ่งใช้ป้าย one_of/group ที่เก็บใน jobs.jd_extraction ได้
"""
import re

from app.agents.llm import structured_invoke
from app.agents.models import JDExtraction, JobRequirement
from app.agents.skills import canonical, is_skill
from app.agents.state import HRSystemState

PROMPT = """คุณคือผู้เชี่ยวชาญ HR อ่านประกาศรับสมัครงานนี้แล้วตอบ:
- job_title: ชื่อตำแหน่ง
- min_experience_years: จำนวนปีประสบการณ์ขั้นต่ำ (ไม่ระบุ = 0, ถ้าเป็นช่วงเช่น 2-5 ปีให้ใช้ตัวน้อย)
- education: ระดับการศึกษาตามที่ประกาศเขียน
- items: ทุกคำในประกาศที่อาจเป็นทักษะ หนึ่งคำต่อหนึ่ง item (ถ้าบรรทัดเดียวมีหลายตัว ให้แยกเป็นหลาย item)

สำหรับแต่ละ item ตอบตามลำดับนี้:

source_line — ยกข้อความในประกาศที่คำนี้อยู่มาตรง ๆ ทั้งบรรทัด (ดูคำว่า or/หรือ/such as/เช่น/is a plus ในบรรทัดนี้)

name — ชื่อทางการ เช่น "PostgreSQL" · เครื่องหมาย "/" เป็นส่วนหนึ่งของชื่อ ห้ามแยก ("CI/CD", "TCP/IP", "PL/SQL")

kind — คำนี้คืออะไร:
  technology      = ภาษา เครื่องมือ เฟรมเวิร์ก แพลตฟอร์ม ผลิตภัณฑ์ (Python, Docker, AWS, LangChain)
  method          = ชื่อวิธีการหรือแนวปฏิบัติที่เขียนในเรซูเม่ได้ (RAG, Prompt Engineering, MLOps,
                    Fine-tuning, CI/CD, Unit Testing, Code Review, Agile)
  knowledge_field = สาขาความรู้ที่เขียนเดี่ยว ๆ (Machine Learning, Deep Learning, NLP)
  duty            = สิ่งที่ต้องทำในงาน เป็นกริยาหรือกิจกรรม ไม่ใช่ทักษะ (monitoring, logging,
                    performance tuning, experimentation, research, build workflows, design solutions)
  category        = ชื่อหมวดที่ตามด้วยตัวอย่างจริง ("Vector databases" ใน "Vector databases such as
                    Pinecone", "cloud platforms" ใน "cloud platforms (AWS, GCP)")
  role            = ชื่อตำแหน่งหรือบทบาทของคน (data scientists, product owners, engineers)
  personal        = อายุ เพศ ชื่อสถาบันการศึกษา หรือคุณลักษณะส่วนตัว
  education       = วุฒิหรือสาขาวิชาที่เรียน (ปริญญาตรี, วิทยาการคอมพิวเตอร์, Computer Science,
                    สาขาคอมพิวเตอร์) — ใส่ใน education แล้ว ไม่ใช่ทักษะ

necessity — ประกาศบอกว่าจำเป็นแค่ไหน (ดูจาก source_line):
  must    = ต้องมี และไม่ได้เป็นตัวเลือก ("A and B", "A และ B", รายการที่ไม่มีคำว่าหรือ,
            "ได้แก่ A, B" ซึ่งคือการระบุครบทุกตัว)
  one_of  = เป็นหนึ่งในตัวเลือก ("A, B, or C", "A หรือ B", "อย่างใดอย่างหนึ่ง", "at least one of", "or similar")
  example = เป็นตัวอย่าง ("such as", "e.g.", "like", "เช่น")
  plus    = เป็นข้อได้เปรียบ ("is a plus", "nice to have", "preferred", "advantage",
            "จะพิจารณาเป็นพิเศษ", "จะได้รับการพิจารณาเป็นพิเศษ")

section — คำนี้อยู่ในส่วนไหนของประกาศ:
  duties         = ใต้หัวข้อหน้าที่/ความรับผิดชอบ/รายละเอียดงาน (Responsibilities, Job Description)
  qualifications = ใต้หัวข้อคุณสมบัติ/ทักษะที่ต้องมี (Qualifications, Requirements, Required Skills)
  unsectioned    = ประกาศไม่ได้แบ่งหัวข้อ และเป็นการบอกคุณสมบัติ (เช่น "Looking for a developer with React")
  ถ้าประกาศไม่มีหัวข้อ แต่บรรทัดนั้นขึ้นต้นด้วยกริยาบอกสิ่งที่ต้องทำ (Develop, Build, Design, Implement,
  Integrate, Conduct, Apply, ออกแบบ, พัฒนา, ดูแล) ให้ถือว่าเป็น duties

group — ถ้า necessity เป็น one_of หรือ example ให้ตั้งชื่อกลุ่มสั้น ๆ ของตัวเลือกที่มาด้วยกัน
  (ใช้ชื่อเดียวกันทุกตัวในกลุ่ม เช่น "cloud") · กรณีอื่นเว้นว่าง

ประกาศรับสมัครงาน:
{raw_jd}"""

# kind ที่ไม่ใช่ทักษะ — ตัดทิ้ง ไม่ว่าประกาศจะบอกว่าจำเป็นแค่ไหน
# education: สาขาที่เรียน (เช่น "วิทยาการคอมพิวเตอร์") ไม่มีใครเขียนเป็นทักษะในเรซูเม่ ถ้าหลุดเข้า
# required ทุกคนจะถูกหักคะแนน (วัดแล้ว 2026-09-19) — วุฒิอยู่ในฟิลด์ education อยู่แล้ว
_NOT_SKILLS = {"duty", "category", "role", "personal", "education"}
# necessity ที่แปลว่าประกาศ "ยกชื่อเทคโนโลยีมาให้" ไม่ใช่สิ่งที่ต้องสร้าง
_LISTED = {"example", "one_of"}

# คำที่บอกว่าเป็นตัวเลือก — ตาข่ายเผื่อ LLM ติดป้าย must ทั้งที่บรรทัดเขียนว่า "A, B or C"
# ("AI, Machine Learning, or Data Science" หลุดมาแบบนี้จริง) · ภาษาไทยไม่มีช่องว่างระหว่างคำ
# จึงเทียบเป็น substring
_OR = re.compile(r"\bor\b|หรือ|อย่างใดอย่างหนึ่ง", re.IGNORECASE)
# แบ่งบรรทัดเป็นท่อน ๆ ให้ "or" มีผลแค่ในท่อนของมัน — จุดต้องตามด้วยช่องว่าง ไม่งั้น "Next.js" ถูกหั่น
_CLAUSE = re.compile(r"\.\s|;|\n")


def _mentions(clause: str, name: str) -> bool:
    """clause มีชื่อนี้เป็นคำ ๆ หนึ่ง — ไม่ใช่เศษของคำอื่น ("SQL" ต้องไม่เจอใน "PostgreSQL",
    "Go" ต้องไม่เจอใน "Google") · ขอบคำเช็กเฉพาะฝั่งที่เป็นตัวอักษรละติน/ตัวเลข เพราะภาษาไทย
    ไม่มีช่องว่างระหว่างคำ"""
    pattern = re.escape(name.casefold())
    if name[:1].isascii() and name[:1].isalnum():
        pattern = r"(?<![a-z0-9])" + pattern
    if name[-1:].isascii() and name[-1:].isalnum():
        pattern += r"(?![a-z0-9])"
    return re.search(pattern, clause.casefold()) is not None


def _in_or_clause(items: list[tuple[str, str]]) -> set[int]:
    """index ของ item ที่อยู่ในท่อนประโยคเดียวกับ or/หรือ ร่วมกับทักษะอื่นจาก **บรรทัดเดียวกัน**.

    - ต้องมี ≥ 2 ทักษะในท่อนเดียวกัน — "ปริญญาตรีสาขาคอมพิวเตอร์หรือสาขาที่เกี่ยวข้อง" มีคำว่าหรือ
      แต่ไม่มีทักษะให้เลือกระหว่างกัน
    - นับเฉพาะ item ที่ source_line เป็นบรรทัดนั้น — "SQL" จากบรรทัด "Python and SQL" ต้องไม่ถูก
      ลากไปด้วยเพราะมีบรรทัดอื่นเขียน "PostgreSQL or MySQL"
    - ชื่อที่ LLM เขียนต่างจากต้นฉบับจะหาไม่เจอ = คงป้ายเดิมไว้
    """
    by_line: dict[str, list[int]] = {}
    for i, (_, line) in enumerate(items):
        by_line.setdefault(line, []).append(i)
    hits: set[int] = set()
    for line, idxs in by_line.items():
        for clause in _CLAUSE.split(line):
            if not _OR.search(clause):
                continue
            inside = [i for i in idxs if _mentions(clause, items[i][0])]
            if len(inside) >= 2:
                hits.update(inside)
    return hits


# คำต่อท้ายทั่วไปที่ทำให้ชื่อทักษะเจาะจงเกินเรซูเม่ — matcher เทียบแบบ "required ต้องไม่เจาะจงกว่า
# owned" จึง "Python Programming" ไม่มีวันตรงกับเรซูเม่ที่เขียน "Python" (ประกาศ JobsDB จริง
# 2026-09-19 ทำให้ทุกคนขาดข้อบังคับข้อนี้) · ตัดเฉพาะคำท้าย และต้องเหลือชื่อไม่ว่าง
_GENERIC_SUFFIX = {"programming", "development", "skills", "skill", "language", "technology", "technologies"}
# ตัดเฉพาะชื่อที่ LLM บอกว่าเป็นทักษะจริง (ไม่แตะ duty/education ซึ่งถูกทิ้งอยู่แล้ว)
_TRIM_KINDS = {"technology", "method", "knowledge_field"}
# ถ้าตัดแล้วเหลือคำกว้างพวกนี้ ห้ามตัด — "Web Development" → "Web" จะไปตรงกับ "Web Scraping"
_BROAD_HEADS = {
    "web", "mobile", "game", "software", "app", "application", "frontend", "front-end",
    "backend", "back-end", "fullstack", "full-stack", "full stack", "system", "systems", "data",
}


def _clean_name(name: str, kind: str) -> str:
    words = name.strip().split()
    if kind not in _TRIM_KINDS:
        return " ".join(words)
    while len(words) > 1 and words[-1].casefold() in _GENERIC_SUFFIX:
        rest = words[:-1]
        if " ".join(rest).casefold() in _BROAD_HEADS:
            break
        words = rest
    return " ".join(words)


_BULLET = re.compile(r"^[\s•*\-–·]+")


def _norm_line(s: str) -> str:
    """บรรทัดในรูปที่เทียบกันได้ — ไม่สนตัวพิมพ์ ช่องว่างซ้ำ และสัญลักษณ์ bullet ต้นบรรทัด."""
    return " ".join(_BULLET.sub("", s).split()).casefold()


def _line_keys(items, raw_jd: str | None) -> list[str]:
    """บรรทัดจริงในประกาศที่แต่ละ item มาจาก (normalize แล้ว).

    กติกาที่อิงบรรทัด (ตาข่าย or/หรือ และ _effective_sections) เคยใช้ source_line ของ LLM ตรง ๆ
    ถ้ามันยกมาไม่ครบหรือยกไม่ตรงกันในแต่ละคำ กติกาจะไม่ทำงานแบบเงียบ ๆ · จึงหาบรรทัดในประกาศ
    ที่มีข้อความที่ยกมา แล้วใช้บรรทัดนั้นทั้งบรรทัด · หาไม่เจอ (หรือไม่มี raw_jd) ใช้ source_line
    ที่ normalize แล้วแทน
    """
    jd_lines = [n for n in (_norm_line(x) for x in (raw_jd or "").splitlines()) if n]
    keys = []
    for it in items:
        quote = _norm_line(it.source_line)
        found = next((ln for ln in jd_lines if len(quote) >= 6 and quote in ln), None)
        keys.append(found or quote)
    return keys


def _effective_sections(items, keys: list[str]) -> list[str]:
    """section ที่ใช้จริงต่อ item — ทำให้คงเส้นคงวาภายในบรรทัดเดียวกัน.

    LLM ติด section ทีละคำ ในประกาศที่ไม่มีหัวข้อ (เช่น AI Engineer 7b44445d จาก JobsDB ที่มีแต่
    "Develop…/Build…") มันติดคำกริยาว่า duties แต่ติด ML/DL ในบรรทัดเดียวกันว่า unsectioned —
    รันสองรอบได้ข้อบังคับ 13 กับ 0 ตัว (gemini-2.5-flash 2026-09-19) · กติกา: item ที่เป็น
    unsectioned ถ้าบรรทัดเดียวกันมีคำที่ถูกติด duties หรือ kind duty → นับเป็น duties
    ไม่แตะ item ที่ติด qualifications — บรรทัดคุณสมบัติอย่าง "Experience building APIs with Python"
    ต้องไม่ถูกลากไปเป็นหน้าที่งาน
    """
    duty_lines = {k for it, k in zip(items, keys) if it.section == "duties" or it.kind == "duty"}
    return [
        "duties" if it.section == "unsectioned" and k in duty_lines else it.section
        for it, k in zip(items, keys)
    ]


def to_requirement(ex: JDExtraction, raw_jd: str | None = None) -> JobRequirement:
    """จัดฝั่ง required/preferred จากป้าย — ฟังก์ชันบริสุทธิ์ กติกาทั้งหมดของการจัดฝั่งอยู่ที่นี่.

    - kind ที่ไม่ใช่ทักษะ (หน้าที่งาน ชื่อหมวด บทบาท คุณลักษณะส่วนตัว สาขาที่เรียน) → ตัดทิ้ง
    - ส่วนหน้าที่งานรับเฉพาะ technology ที่ประกาศยกเป็นตัวอย่าง/ตัวเลือก ("LLMs such as GPT, Claude",
      "frameworks such as LangChain") — ที่เหลือในส่วนนั้นคือสิ่งที่ต้องสร้างหรือวลีลอย ๆ ("Build AI
      Chatbots", "Integrate with ERP", "low-latency") ซึ่งวัดแล้ว (gemini-2.5-flash 2026-09-19) ทำให้
      ฝั่ง preferred บวมเป็น 40 กว่าตัวจนคะแนนโบนัสเจือจาง
    - must และไม่ได้มาจากส่วนหน้าที่งาน และไม่อยู่ในท่อน "or/หรือ" → required
    - one_of / example / plus / ส่วนหน้าที่งาน / ท่อน "or/หรือ" → preferred
      (ประกาศสั้นที่ไม่แบ่งหัวข้อเป็น unsectioned จึงยังได้ required ตามปกติ)
    - ตัดซ้ำด้วย skills.canonical ข้ามสองฝั่ง ฝั่ง required ชนะ · กรองด้วย is_skill เป็นตาข่ายชั้นสอง
    ไม่แยกสตริงเองเลย "CI/CD" จึงไม่มีทางถูกแยก
    """
    keys = _line_keys(ex.items, raw_jd)
    kept = []
    for item, key, section in zip(ex.items, keys, _effective_sections(ex.items, keys)):
        name = _clean_name(item.name, item.kind)
        if not name or item.kind in _NOT_SKILLS or not is_skill(name):
            continue
        if section == "duties" and not (item.kind == "technology" and item.necessity in _LISTED):
            continue
        kept.append((item.model_copy(update={"section": section, "source_line": key}), name))

    in_or_clause = _in_or_clause([(name, item.source_line) for item, name in kept])

    required: list[str] = []
    preferred: list[str] = []
    for i, (item, name) in enumerate(kept):
        if item.necessity == "must" and item.section != "duties" and i not in in_or_clause:
            required.append(name)
        else:
            preferred.append(name)

    seen: set[str] = set()

    def dedupe(names: list[str]) -> list[str]:
        out = []
        for n in names:
            key = canonical(n)
            if key and key not in seen:
                seen.add(key)
                out.append(n)
        return out

    req = dedupe(required)  # ต้องมาก่อน preferred เพื่อให้ฝั่ง required ชนะ
    pref = dedupe(preferred)
    return JobRequirement(
        job_title=ex.job_title,
        min_experience_years=max(0, ex.min_experience_years),
        required_skills=req,
        preferred_skills=pref,
        education=ex.education,
    )


def extract_jd(raw_jd: str) -> tuple[JobRequirement, JDExtraction]:
    """เรียก LLM หนึ่งครั้ง คืนทั้งผลที่จัดฝั่งแล้วและป้ายดิบ (create_job เก็บป้ายลง jobs.jd_extraction)."""
    ex = structured_invoke(PROMPT.format(raw_jd=raw_jd), JDExtraction)
    return to_requirement(ex, raw_jd), ex


def analyze_jd(state: HRSystemState) -> dict:
    # รันแบบต่อผู้สมัคร: ถ้ามีผลวิเคราะห์ JD ส่งมาแล้ว ให้ข้าม (ไม่เรียก LLM ซ้ำ)
    if state.get("analyzed_jd"):
        return {}
    requirement, _ = extract_jd(state["raw_jd"])
    return {"analyzed_jd": requirement.model_dump()}
