"""Node 1: JD Analyzer — แปลง JD ดิบเป็น JobRequirement (structured).

ทำสองจังหวะใน LLM call เดียว:
1. LLM ติดป้ายทุกคำที่อาจเป็นทักษะ (JDExtraction) — ตอบคำถามแคบ ๆ ต่อคำ ไม่ตัดสินฝั่ง
2. `to_requirement` (โค้ด บริสุทธิ์) จัดฝั่ง required/preferred จากป้าย

ทำไมไม่ให้ LLM ตัดสินฝั่งเอง: `JobRequirement` เป็นรายการแบนที่ทุกข้อบังคับครบ (AND) และ
gemini-2.5-flash-lite ทำตามกติกายาว ๆ ได้ไม่ครบ (วัดแล้ว 2026-09-19 — memory-bank/06)
กติกาที่ย้ายมาอยู่ในโค้ดจึงเทสได้และไม่ขึ้นกับว่าโมเดลจำได้หรือไม่
ตัวเลือก "A หรือ B" รวมเป็นกลุ่ม "A | B" = 1 ข้อ (skills.alternatives) ข้อบังคับ "ต้องมีสักตัว" จึงยังอยู่
"""
import re

from app.agents.llm import structured_invoke, structured_invoke_once
from app.agents.models import JDExtraction, JobRequirement
from app.agents.skills import GROUP_SEP, alternatives, canonical, is_skill
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
# แบ่งที่ "and"/"และ" ด้วย: "Python and PyTorch, TensorFlow, or Hugging Face" → Python ต้องยังเป็น
# ข้อบังคับ (ไม่แบ่งที่ "and/or" ซึ่งแปลว่าเป็นตัวเลือก)
# แบ่งที่ ":" ด้วย: ประกาศที่รายการทักษะถูกวางต่อกันในบรรทัดเดียว ("Core Web: HTML5, CSS3
# Responsive Design: Bootstrap หรือ Tailwind Version Control: Git") เดิมกลายเป็นท่อนเดียว
# แล้ว "หรือ" ตัวเดียวดูดทักษะทั้งบรรทัดเป็นกลุ่มเดียว 16 ตัว (Junior Web Developer 2026-09-22)
_CLAUSE = re.compile(r"\.\s|;|:|\n|\band\b(?!/)|และ", re.IGNORECASE)


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


def _is_label(line: str, name: str) -> bool:
    """ชื่อนี้ถูกใช้เป็นหัวข้อย่อยในบรรทัด ("Version Control: ...", "Back-end Basics (พื้นฐาน):")."""
    n = name.strip().casefold()
    if not n:
        return False
    return re.search(re.escape(n) + r"\s*(\([^)]*\))?\s*:", line.casefold()) is not None


# คำที่ใช้ตั้งชื่อหมวด แต่ไม่มีใครใช้เป็นชื่อทักษะ — หัวข้อที่ลงท้ายด้วยคำพวกนี้ถูกตัดแม้อยู่ในกลุ่ม
# ตัวเลือก ("Back-end Basics: Node.js หรือ PHP") · อังกฤษดูคำสุดท้ายของแต่ละท่อนที่คั่นด้วย "&"
# ("Tooling & Build") ไม่ดูทุกคำ เพราะ "Knowledge Graph" เป็นทักษะจริง · ไทยดูว่ามีคำนี้อยู่ในชื่อ
_HEADING_WORDS_EN = {
    "basics", "basic", "fundamentals", "essentials", "tools", "tooling",
    "framework", "frameworks", "handling", "knowledge", "skills",
}
_HEADING_WORDS_TH = ("พื้นฐาน", "ความรู้", "เครื่องมือ", "ทักษะ")


def _is_generic_heading_name(name: str) -> bool:
    n = name.casefold()
    if any(w in n for w in _HEADING_WORDS_TH):
        return True
    parts = re.split(r"&|\band\b|/", n)
    return any(p.split() and p.split()[-1] in _HEADING_WORDS_EN for p in parts)


def _heading_items(kept) -> set[int]:
    """index ของ item ที่เป็นหัวข้อย่อยนำหน้ารายการทักษะ — "Version Control: Git, GitHub / GitLab".

    ต้องตามด้วย ":" **และ** หลัง ":" ในบรรทัดเดียวกันมีทักษะอื่นที่เก็บไว้ต่อท้าย
    เงื่อนไขหลังกัน "Python: 3+ years" / "SQL: ระดับดี" — ชื่อที่ตามด้วย ":" แต่ไม่มีทักษะอื่นตามมา
    คือทักษะจริงที่บอกระดับ ถ้าตัดทิ้งทักษะจะหายจากเกณฑ์แบบเงียบ ๆ
    หัวข้อที่อยู่บรรทัดเดี่ยว ("Version Control:" แล้วรายการอยู่บรรทัดถัดไป) ไม่ตัด — เลือกฝั่งปลอดภัย
    ผู้เรียกตัดเฉพาะหัวข้อที่ไม่ได้อยู่ในกลุ่มตัวเลือก ("Responsive Design: Bootstrap หรือ Tailwind"
    ยังเป็นตัวเลือกร่วมกับกลุ่ม — ผู้สมัครที่เขียนแค่ Responsive Design ก็ผ่านข้อนั้น)
    """
    out: set[int] = set()
    for i, (item, name) in enumerate(kept):
        line = item.source_line.casefold()
        m = re.search(re.escape(name.strip().casefold()) + r"\s*(\([^)]*\))?\s*:", line)
        if not m:
            continue
        tail = line[m.end():]
        if any(
            j != i and other.source_line == item.source_line and other_name != name
            and _mentions(tail, other_name)
            for j, (other, other_name) in enumerate(kept)
        ):
            out.add(i)
    return out


def _or_clauses(items: list[tuple[str, str]]) -> list[list[int]]:
    """กลุ่ม index ของ item ที่อยู่ในท่อนประโยคเดียวกับ or/หรือ ร่วมกับทักษะอื่นจาก **บรรทัดเดียวกัน**.

    แต่ละท่อนคือตัวเลือกหนึ่งกลุ่ม — ตาข่ายเผื่อ LLM ไม่ได้ติดป้าย one_of/group ให้

    - ต้องมี ≥ 2 ทักษะในท่อนเดียวกัน — "ปริญญาตรีสาขาคอมพิวเตอร์หรือสาขาที่เกี่ยวข้อง" มีคำว่าหรือ
      แต่ไม่มีทักษะให้เลือกระหว่างกัน
    - นับเฉพาะ item ที่ source_line เป็นบรรทัดนั้น — "SQL" จากบรรทัด "Python and SQL" ต้องไม่ถูก
      ลากไปด้วยเพราะมีบรรทัดอื่นเขียน "PostgreSQL or MySQL"
    - ชื่อที่ LLM เขียนต่างจากต้นฉบับจะหาไม่เจอ = คงป้ายเดิมไว้
    """
    by_line: dict[str, list[int]] = {}
    for i, (_, line) in enumerate(items):
        by_line.setdefault(line, []).append(i)
    groups: list[list[int]] = []
    for line, idxs in by_line.items():
        clauses = _CLAUSE.split(line)
        members: list[list[int]] = [[] for _ in clauses]
        for i in idxs:
            name = items[i][0]
            hits = [k for k, c in enumerate(clauses) if _mentions(c, name)]
            if not hits:
                continue
            # ชื่อที่ตามด้วย ":" คือหัวข้อย่อยของท่อน "ถัดไป" ("Responsive Design: Bootstrap หรือ
            # Tailwind" → หัวข้อเป็นตัวเลือกร่วมกับ Bootstrap/Tailwind) · ถ้าทักษะถูกวางต่อกัน
            # ในบรรทัดเดียว หัวข้อจะติดท้ายท่อนก่อนหน้า — นับไว้ท่อนนั้นจะถูกดูดเข้ากลุ่มผิดกลุ่ม
            if _is_label(line, name):
                hits = [k + 1 for k in hits if k + 1 < len(clauses)]
            for k in hits:
                members[k].append(i)
        for clause, inside in zip(clauses, members):
            if _OR.search(clause) and len(inside) >= 2:
                groups.append(inside)
    return groups


def _group_ids(kept) -> list[int]:
    """เลขกลุ่มของแต่ละ item (union-find) — รวมจากสองแหล่ง:
    ป้าย group ที่ LLM ติด (one_of/example ในบรรทัดเดียวกัน) และท่อน or/หรือ ที่โค้ดหาเอง
    item ที่ไม่อยู่ในกลุ่มไหนได้เลขของตัวเอง
    """
    parent = list(range(len(kept)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    by_label: dict[tuple[str, str], int] = {}
    for i, (item, _) in enumerate(kept):
        label = item.group.strip().casefold()
        if label and item.necessity in _LISTED:
            key = (label, item.source_line)
            if key in by_label:
                union(i, by_label[key])
            else:
                by_label[key] = i
    for clause in _or_clauses([(name, item.source_line) for item, name in kept]):
        for i in clause[1:]:
            union(i, clause[0])
    return [find(i) for i in range(len(kept))]


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


# หัวข้อย่อยที่บอกว่าทักษะข้างใต้เป็น "ข้อได้เปรียบ" — ใช้คู่กับ _preferred_lines
_PREFERRED_HEADING = (
    "nice to have", "nice-to-have", "good to have", "good-to-have", "preferred", "bonus",
    "advantage", "desirable", "optional", "a plus",
    "แต้มต่อ", "ข้อได้เปรียบ", "พิจารณาเป็นพิเศษ", "ทักษะเสริม", "ไม่บังคับ",
)
# หัวข้อที่ปิดช่วง "ข้อได้เปรียบ" — ข้อบังคับ หรือหมวดอื่นของประกาศ
_OTHER_HEADING = (
    "must-have", "must have", "required", "requirement", "qualification", "responsibilit",
    "soft skill", "benefit", "how to apply",
    "จำเป็น", "ต้องมี", "คุณสมบัติ", "หน้าที่", "ความรับผิดชอบ", "สวัสดิการ", "วิธีสมัคร",
)
# บรรทัดสั้นแค่ไหนถึงนับเป็นหัวข้อได้ แม้ไม่ลงท้ายด้วย ":" ("🤝 Soft Skills", "3. สวัสดิการ")
_HEADING_MAX_CHARS = 50
# อีโมจิ เลขข้อ จุด ต้นบรรทัด ("🛠 ", "2. ") — ตัดก่อนดูว่าหัวข้อขึ้นต้นด้วยคำอะไร
_LEADING_NON_WORD = re.compile(r"^[\W\d_]+")


def _preferred_lines(raw_jd: str | None) -> set[str]:
    """บรรทัด (normalize แล้ว) ที่อยู่ใต้หัวข้อ "ข้อได้เปรียบ" ในประกาศ — ทักษะในบรรทัดเหล่านี้ไปฝั่งอยากได้.

    ทำไมต้องมี: LLM ติดป้ายทีละคำจากบรรทัดของคำนั้น แต่ประกาศที่แบ่งเป็นหัวข้อ
    ("Nice-to-Have:" แล้วตามด้วย "Front-end Framework: React.js, Vue.js, หรือ Next.js")
    ไม่มีคำว่า nice to have อยู่ในบรรทัดทักษะเลย · และป้าย necessity มีช่องเดียว ตัวเลือกแบบ
    "หรือ" ใต้หัวข้อนี้จึงถูกติด one_of แล้วนับเป็นข้อบังคับ (วัดจริง: Junior Web Developer
    2026-09-22 สองรอบ ฝั่งอยากได้ได้ 3 กับ 0 ตัว จากที่ควรเป็น 7 กลุ่ม)

    กติกา: บรรทัดที่ "ดูเป็นหัวข้อ" (ลงท้ายด้วย ":" หรือสั้นและไม่มีจุลภาค) ที่มีคำบอกข้อได้เปรียบ
    เปิดช่วง · หัวข้อข้อบังคับ/หมวดอื่นปิดช่วง · หัวข้ออื่นที่ไม่มีคำบอกอะไร (เช่น "Tools:")
    ไม่เปลี่ยนช่วง · บรรทัดที่ขึ้นต้นด้วยคำบอกข้อได้เปรียบตามด้วย ":" แล้วมีทักษะต่อท้าย
    ("Nice to have: Docker, K8s") นับเฉพาะบรรทัดนั้น
    ประโยคในบรรทัดเดียวอย่าง "Docker is a plus" ไม่เปิดช่วง (ไม่ดูเป็นหัวข้อ) — LLM ติด plus ให้ได้อยู่แล้ว
    """
    out: set[str] = set()
    in_preferred = False
    for raw in (raw_jd or "").splitlines():
        line = _norm_line(raw)
        if not line:
            continue
        head, colon, tail = line.partition(":")
        is_pref = any(m in head for m in _PREFERRED_HEADING)
        is_other = any(m in head for m in _OTHER_HEADING)
        short = not colon and len(line) <= _HEADING_MAX_CHARS and "," not in line
        if short and is_pref:
            # ไม่มี ":" ต้องขึ้นต้นด้วยคำบอกข้อได้เปรียบ ("Nice to have", "🌟 Bonus skills")
            # ไม่งั้นประโยคสั้นอย่าง "Docker is a plus" จะกลายเป็นหัวข้อแล้วลากบรรทัดถัดไปทั้งหมด
            lead = _LEADING_NON_WORD.sub("", line)
            is_pref = any(lead.startswith(m) for m in _PREFERRED_HEADING)
        headingish = (colon and not tail.strip()) or short
        if headingish and (is_pref or is_other):
            in_preferred = is_pref  # หัวข้อที่มีทั้งสองคำ ("Preferred Qualifications") = ข้อได้เปรียบ
            continue
        if in_preferred or (colon and tail.strip() and is_pref):
            out.add(line)
    return out


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
    - อยู่ใต้หัวข้อ "Nice-to-Have / แต้มต่อ / ข้อได้เปรียบ" ในประกาศ → preferred เสมอ ไม่ว่าป้ายจะเป็นอะไร
      (โค้ดอ่านหัวข้อจาก raw_jd เอง ดู _preferred_lines)
    - ตัดซ้ำด้วย skills.canonical ข้ามสองฝั่ง ฝั่ง required ชนะ · กรองด้วย is_skill เป็นตาข่ายชั้นสอง
    ไม่แยกสตริงเองเลย "CI/CD" จึงไม่มีทางถูกแยก
    """
    keys = _line_keys(ex.items, raw_jd)
    preferred_lines = _preferred_lines(raw_jd)
    kept = []
    for item, key, section in zip(ex.items, keys, _effective_sections(ex.items, keys)):
        name = _clean_name(item.name, item.kind)
        if not name or item.kind in _NOT_SKILLS or not is_skill(name):
            continue
        if section == "duties" and not (item.kind == "technology" and item.necessity in _LISTED):
            continue
        kept.append((item.model_copy(update={"section": section, "source_line": key}), name))

    # รวมตัวเลือกเป็นกลุ่ม "A | B | C" = 1 ข้อ มีตัวใดตัวหนึ่งก็ผ่าน (ทางแก้ข้อ 3)
    # หัวข้อที่เป็นคำกว้าง ("Back-end Basics:", "Database Basics:") ตัดก่อนจัดกลุ่ม ไม่งั้นมันเข้าไป
    # เป็นตัวเลือกในกลุ่มของท่อนถัดไป · หัวข้อที่เป็นทักษะจริง ("Responsive Design:") ยังอยู่
    generic = {i for i in _heading_items(kept) if _is_generic_heading_name(kept[i][1])}
    kept = [k for i, k in enumerate(kept) if i not in generic]

    ids = _group_ids(kept)
    headings = _heading_items(kept)
    members: dict[int, list[int]] = {}
    for i, g in enumerate(ids):
        members.setdefault(g, []).append(i)

    required: list[str] = []
    preferred: list[str] = []
    done: set[int] = set()
    for i, g in enumerate(ids):  # วนตามลำดับในประกาศ กลุ่มอยู่ตำแหน่งของตัวแรก
        if g in done:
            continue
        done.add(g)
        idxs = members[g]
        items = [kept[j][0] for j in idxs]
        names = list(dict.fromkeys(kept[j][1] for j in idxs))
        if len(names) == 1 and idxs[0] in headings:
            continue  # หัวข้อย่อยที่มีทักษะต่อท้าย ไม่ใช่ทักษะ ("Version Control: Git, GitHub")
        if len(names) == 1:
            # ตัวเดียว: must นอกส่วนหน้าที่ → ต้องมี · one_of/example/plus ลอย ๆ → อยากได้
            # (ตัวที่ตาข่าย or ดึงมาจะไม่เหลือตัวเดียว เพราะท่อนต้องมี ≥ 2 ทักษะ)
            is_req = items[0].necessity == "must" and items[0].section != "duties"
        else:
            # กลุ่มเป็นข้อบังคับเมื่อทุกตัวเป็น must/one_of และไม่อยู่ในส่วนหน้าที่งาน
            # "such as" (example) / "is a plus" / ส่วนหน้าที่งาน → กลุ่มฝั่งอยากได้
            is_req = all(it.necessity in ("must", "one_of") and it.section != "duties" for it in items)
        # ใต้หัวข้อข้อได้เปรียบ → อยากได้เสมอ (source_line ของ kept คือบรรทัดจริงจาก _line_keys แล้ว)
        if any(it.source_line in preferred_lines for it in items):
            is_req = False
        (required if is_req else preferred).append(f" {GROUP_SEP} ".join(names))

    seen: set[str] = set()

    def dedupe(names: list[str]) -> list[str]:
        out = []
        for n in names:
            # กลุ่มเทียบซ้ำแบบไม่สนลำดับตัวเลือก
            key = GROUP_SEP.join(sorted(canonical(a) for a in alternatives(n)))
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


def extract_jd(raw_jd: str, once: bool = False) -> tuple[JobRequirement, JDExtraction]:
    """เรียก LLM หนึ่งครั้ง คืนทั้งผลที่จัดฝั่งแล้วและป้ายดิบ (create_job เก็บป้ายลง jobs.jd_extraction).

    once=True = ไม่ retry — ใช้กับปุ่มที่ HR นั่งรอหน้าจอ (อ่านประกาศใหม่) ให้รู้ผลเร็วถ้าล้ม
    """
    invoke = structured_invoke_once if once else structured_invoke
    ex = invoke(PROMPT.format(raw_jd=raw_jd), JDExtraction)
    return to_requirement(ex, raw_jd), ex


def analyze_jd(state: HRSystemState) -> dict:
    # รันแบบต่อผู้สมัคร: ถ้ามีผลวิเคราะห์ JD ส่งมาแล้ว ให้ข้าม (ไม่เรียก LLM ซ้ำ)
    if state.get("analyzed_jd"):
        return {}
    requirement, _ = extract_jd(state["raw_jd"])
    return {"analyzed_jd": requirement.model_dump()}
