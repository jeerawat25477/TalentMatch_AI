"""การเทียบทักษะแบบ deterministic (ไม่เรียก LLM) — ใช้โดยโหนด matcher.

เดิม matcher เทียบด้วย substring สองทาง (`n in o or o in n`) ซึ่งพังกับข้อมูลจริง:
required "R" ถูกนับว่าตรงกับ docke*r*, langg*r*aph, redis, postg*r*esql และ "ML" ตรงกับ ht*ml*

ทางแก้ที่นี่คือเทียบบน **ขอบเขตคำ (token)** แทนตัวอักษร แล้วเติมสองตารางเพื่อรับ
กรณีที่ขอบเขตคำอย่างเดียวไม่พอ:
- ALIASES  — ชื่อเดียวกันแต่สะกดต่าง (NodeJs / Node.js, Postgres / PostgreSQL)
- IMPLIES  — ทักษะที่ครอบคลุมอีกทักษะโดยปริยาย (รู้ PostgreSQL ย่อมเขียน SQL ได้)

หมายเหตุ: ไม่ใช้ embeddings ที่นี่โดยตั้งใจ — วัด cosine ของ gemini-embedding-001 แล้ว
PostgreSQL↔MySQL (0.885) และ Java↔JavaScript (0.865) สูงกว่าคู่ที่ควรตรงจริงอย่าง
React Native↔Mobile Hybrid (0.838) จึงไม่มี threshold ใดที่ใช้ได้ ดู memory-bank/02_progress.md
"""
import re

# สะกดต่าง/ชื่อเล่น -> ชื่อมาตรฐาน (เทียบหลัง normalize: ตัวเล็ก, ตัดอักขระพิเศษเป็นช่องว่าง)
ALIASES: dict[str, str] = {
    # ภาษา / runtime
    "js": "javascript",
    "ts": "typescript",
    "golang": "go",
    "py": "python",
    "node": "node js",
    "nodejs": "node js",
    "node js": "node js",
    "c sharp": "c#",
    "csharp": "c#",
    "net": "dotnet",  # ".NET" normalize แล้วเหลือ "net"
    "asp net": "dotnet",
    "nextjs": "next js",
    # ฐานข้อมูล
    "postgres": "postgresql",
    "psql": "postgresql",
    "postgre": "postgresql",
    "postgresql": "postgresql",
    "mssql": "sql server",
    "ms sql": "sql server",
    "microsoft sql server": "sql server",
    "mongo": "mongodb",
    # คลาวด์ / infra
    "k8s": "kubernetes",
    "microsoft azure": "azure",
    "azure": "azure",
    "amazon web services": "aws",
    "google cloud platform": "gcp",
    "google cloud": "gcp",
    # เครื่องมือ BI / data
    "powerbi": "power bi",
    "power bi": "power bi",
    "ms excel": "excel",
    "microsoft excel": "excel",
    # AI / ML
    "ml": "machine learning",
    "dl": "deep learning",
    "llm": "llms",
    "llms": "llms",
    "genai": "generative ai",
    "gen ai": "generative ai",
    "nlp": "natural language processing",
    "rest": "rest api",
    "restful api": "rest api",
    "restful apis": "rest api",
    "apis": "api",
}

# ทักษะ -> ทักษะที่ถือว่าครอบคลุมโดยปริยาย (ทางเดียว: ซ้ายมี => ขวามี)
IMPLIES: dict[str, set[str]] = {
    "postgresql": {"sql", "database"},
    "mysql": {"sql", "database"},
    "sql server": {"sql", "database"},
    "oracle": {"sql", "database"},
    "mongodb": {"nosql", "database"},
    "redis": {"nosql", "database"},
    "fastapi": {"python", "rest api", "api"},
    "django": {"python", "rest api", "api"},
    "flask": {"python", "rest api", "api"},
    "langgraph": {"langchain"},
    "react native": {"react"},
    "next js": {"react"},
    "typescript": {"javascript"},
    "kubernetes": {"docker"},
    "power bi": {"dax", "power query", "data visualization"},
    "pytorch": {"deep learning", "machine learning"},
    "tensorflow": {"deep learning", "machine learning"},
    "deep learning": {"machine learning"},
    "scikit learn": {"machine learning"},
}

# คำที่ LLM มักหลุดมาใน required_skills ทั้งที่เป็น "คนที่ต้องร่วมงาน" ไม่ใช่ทักษะ
# (เจอจริงใน DB: data scientists, engineers, product owners, solution architects)
# ถูกนับเป็นตัวหารของสูตรคะแนน จึงกดคะแนนทุกคนลงโดยไม่มีเหตุผล
NON_SKILL_WORDS: frozenset[str] = frozenset(
    {
        "scientist", "scientists",
        "engineer", "engineers",
        "developer", "developers",
        "owner", "owners",
        "architect", "architects",
        "manager", "managers",
        "analyst", "analysts",
        "stakeholder", "stakeholders",
        "designer", "designers",
        "team", "teams",
        "colleague", "colleagues",
    }
)

# คง # และ + ไว้เพราะเป็นส่วนหนึ่งของชื่อจริง (C#, C++) ที่เหลือกลายเป็นตัวคั่น
# จุดและขีดกลางต้องกลายเป็นช่องว่าง ไม่งั้น "Node.js" จะไม่มีวันตรงกับ "NodeJs"
_PUNCT = re.compile(r"[^0-9a-z#+฀-๿]+")


def _normalize(s: str) -> str:
    """ตัวเล็ก + ยุบอักขระคั่นเป็นช่องว่างเดียว."""
    return " ".join(_PUNCT.sub(" ", s.lower()).split())


def canonical(skill: str) -> str:
    """ชื่อมาตรฐานของทักษะ — normalize แล้วแมปผ่าน ALIASES.

    ต้องทำก่อน tokenize เสมอ ไม่งั้น "NodeJs" (1 token) จะไม่มีวันตรงกับ "Node.js" (2 token)
    """
    n = _normalize(skill)
    return ALIASES.get(n, n)


def _tokens(skill: str) -> list[str]:
    return canonical(skill).split()


def is_skill(s: str) -> bool:
    """False ถ้าเป็นชื่อบทบาท/ตำแหน่งของคน ไม่ใช่ทักษะ.

    ใช้กรอง parsed_criteria ตอนอ่านจาก DB ด้วย เพื่อให้ JD เก่าที่บันทึกไว้แล้ว
    ได้คะแนนที่ถูกต้องทันทีโดยไม่ต้องเรียก LLM วิเคราะห์ใหม่
    """
    toks = _tokens(s)
    if not toks:
        return False
    # ตัดเฉพาะเมื่อ "คำสุดท้าย" เป็นชื่อบทบาท เช่น "data scientists", "solution architects"
    # ไม่ตัด "developer tools" หรือ "team city" ที่คำบทบาทเป็นคำขยาย
    return toks[-1] not in NON_SKILL_WORDS


def _covers(required_toks: list[str], owned: str) -> bool:
    """token ของ required ปรากฏเรียงติดกันใน token ของ owned หรือไม่.

    ทางเดียวเท่านั้น (owned ต้องเจาะจงเท่ากับหรือมากกว่า required):
      required "SQL" ⊆ owned "SQL Server"      -> True  (รู้ SQL Server ก็เขียน SQL ได้)
      required "React Native" vs owned "React" -> False (รู้ React ไม่ได้แปลว่าทำ RN เป็น)
    เทียบบน token จึงไม่มีทางที่ "r" จะไปโผล่ใน "docker" ได้อีก
    """
    owned_toks = canonical(owned).split()
    n = len(required_toks)
    if n == 0 or n > len(owned_toks):
        return False
    return any(owned_toks[i : i + n] == required_toks for i in range(len(owned_toks) - n + 1))


def matches(required: str, owned: set[str]) -> bool:
    """ผู้สมัครที่มีทักษะ `owned` ถือว่ามีทักษะ `required` หรือไม่."""
    req = canonical(required)
    if not req:
        return False
    req_toks = req.split()

    for o in owned:
        can_o = canonical(o)
        if req == can_o:
            return True
        if req in IMPLIES.get(can_o, ()):
            return True
        if _covers(req_toks, can_o):
            return True
    return False


def split_matched(required: list[str], owned: set[str]) -> tuple[list[str], list[str]]:
    """คืน (ทักษะที่ตรง, ทักษะที่ขาด) โดยกรองคำที่ไม่ใช่ทักษะออกก่อน.

    คงข้อความต้นฉบับไว้ (ไม่คืนรูป canonical) เพราะ gap_analysis ถูกส่งต่อไปให้
    planner/drafter เขียนเป็นภาษาคน และแสดงบน radar chart ของ frontend
    """
    real = [s for s in required if is_skill(s)]
    hit = [s for s in real if matches(s, owned)]
    miss = [s for s in real if not matches(s, owned)]
    return hit, miss
