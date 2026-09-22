"""jd_analyzer: LLM ติดป้ายทีละคำ แล้ว to_requirement จัดฝั่งด้วยโค้ด + คำเตือนเกณฑ์บน JobOut.

เทสนี้พิสูจน์กติกาการจัดฝั่ง (โค้ด) ได้ครบ แต่พิสูจน์ไม่ได้ว่า Gemini ติดป้ายถูก —
นั่นต้องรันกับโมเดลจริง (memory-bank/06_scoring_criteria.md)
"""
from datetime import datetime, timezone
from itertools import product
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agents.models import JDExtraction, JDSkillItem, JobRequirement
from app.agents.nodes import jd_analyzer
from app.agents.nodes.jd_analyzer import to_requirement
from app.auth import get_current_user
from app.database import get_conn
from app.main import app
from app.schemas import JobOut

SKILL_KINDS = ("technology", "method", "knowledge_field")
NON_SKILL_KINDS = ("duty", "category", "role", "personal", "education")
NECESSITIES = ("must", "one_of", "example", "plus")
SECTIONS = ("duties", "qualifications", "unsectioned")


def item(name, kind="technology", necessity="must", section="qualifications", group="", line=None):
    return JDSkillItem(source_line=line if line is not None else name, name=name, kind=kind,
                       necessity=necessity, section=section, group=group)


def ex(*items, title="T"):
    return JDExtraction(job_title=title, min_experience_years=2, education="ป.ตรี", items=list(items))


# ---------- กติกาการจัดฝั่ง ----------


@pytest.mark.parametrize("kind,necessity,section", list(product(SKILL_KINDS, NECESSITIES, SECTIONS)))
def test_skill_kinds_side_matrix(kind, necessity, section):
    r = to_requirement(ex(item("Python", kind, necessity, section)))
    if section == "duties" and not (kind == "technology" and necessity in ("example", "one_of")):
        # ส่วนหน้าที่งานรับเฉพาะเทคโนโลยีที่ยกเป็นตัวอย่าง/ตัวเลือก — ที่เหลือทำให้ preferred บวม
        assert (r.required_skills, r.preferred_skills) == ([], [])
    elif necessity == "must" and section != "duties":
        assert (r.required_skills, r.preferred_skills) == (["Python"], [])
    else:
        assert (r.required_skills, r.preferred_skills) == ([], ["Python"])


@pytest.mark.parametrize("kind,necessity,section", list(product(NON_SKILL_KINDS, NECESSITIES, SECTIONS)))
def test_non_skill_kinds_always_dropped(kind, necessity, section):
    r = to_requirement(ex(item("monitoring", kind, necessity, section)))
    assert r.required_skills == [] and r.preferred_skills == []


def test_or_group_becomes_one_required_item_and_examples_a_preferred_group():
    """ตัวอย่างจริงของ AI Engineer 6c0d205a: "Python and SQL" + "Azure, AWS, or GCP" + vector DB such as."""
    cloud = "Microsoft Azure, AWS, or Google Cloud Platform"
    vdb = "Vector databases such as Pinecone, Milvus"
    r = to_requirement(ex(
        item("Python"), item("SQL"),
        item("Microsoft Azure", necessity="one_of", group="cloud", line=cloud),
        item("AWS", necessity="one_of", group="cloud", line=cloud),
        item("Google Cloud Platform", necessity="one_of", group="cloud", line=cloud),
        item("Vector databases", kind="category", line=vdb),
        item("Pinecone", necessity="example", group="vector db", line=vdb),
        item("Milvus", necessity="example", group="vector db", line=vdb),
    ))
    assert r.required_skills == ["Python", "SQL", "Microsoft Azure | AWS | Google Cloud Platform"]
    assert r.preferred_skills == ["Pinecone | Milvus"]


def test_group_labels_only_merge_within_the_same_line():
    """ชื่อกลุ่มซ้ำกันคนละบรรทัด (LLM ตั้งชื่อ "tools" ซ้ำ) ต้องไม่ถูกรวมเป็นกลุ่มเดียว."""
    r = to_requirement(ex(
        item("Airflow", necessity="example", group="tools", line="orchestration such as Airflow"),
        item("Terraform", necessity="example", group="tools", line="IaC such as Terraform"),
    ))
    assert r.preferred_skills == ["Airflow", "Terraform"]


def test_group_in_duties_or_plus_goes_to_preferred():
    duties = "Design systems using LLMs such as GPT, Claude, or Gemini"
    plus = "Experience in ICT, Telecommunications, or Smart City is a plus"
    r = to_requirement(ex(
        *(item(n, necessity="example", section="duties", group="llm", line=duties)
          for n in ("GPT", "Claude", "Gemini")),
        *(item(n, kind="knowledge_field", necessity="plus", line=plus)
          for n in ("ICT", "Telecommunications", "Smart City")),
    ))
    assert r.required_skills == []
    assert r.preferred_skills == ["GPT | Claude | Gemini", "ICT | Telecommunications | Smart City"]


def test_duplicate_groups_in_any_order_are_merged():
    r = to_requirement(ex(
        item("AWS", necessity="one_of", line="AWS or GCP"), item("GCP", necessity="one_of", line="AWS or GCP"),
        item("GCP", necessity="one_of", line="GCP or AWS"), item("AWS", necessity="one_of", line="GCP or AWS"),
    ))
    assert r.required_skills == ["AWS | GCP"]


def test_short_unsectioned_jd_keeps_required():
    """ประกาศย่อหน้าเดียวต้องไม่เหลือ required ว่าง — ไม่งั้นคนที่ไม่มีทักษะเสริมได้ 0."""
    r = to_requirement(ex(item("React", section="unsectioned"),
                          item("Next.js", necessity="plus", section="unsectioned")))
    assert r.required_skills == ["React"] and r.preferred_skills == ["Next.js"]


def test_slash_names_are_never_split():
    r = to_requirement(ex(item("CI/CD", kind="method"), item("TCP/IP"), item("PL/SQL", necessity="plus")))
    assert r.required_skills == ["CI/CD", "TCP/IP"] and r.preferred_skills == ["PL/SQL"]


def test_dedupe_across_sides_required_wins():
    r = to_requirement(ex(
        item("Docker", necessity="plus"),  # มาก่อนแต่เป็น preferred
        item("docker"),                    # ตัวเดียวกันเป็น required — ต้องชนะ
        item("Python"), item("Python", section="duties"),
    ))
    assert r.required_skills == ["docker", "Python"]
    assert r.preferred_skills == []


def test_education_field_is_not_a_skill():
    """วัดจริง: "วิทยาการคอมพิวเตอร์" หลุดเข้า required แล้วทุกคนถูกหักคะแนน."""
    r = to_requirement(ex(item("วิทยาการคอมพิวเตอร์", kind="education"), item("Python")))
    assert r.required_skills == ["Python"] and r.preferred_skills == []


def test_duties_keep_only_listed_technologies():
    """วัดจริง: "low-latency" (7b44445d), "Build AI Chatbots" / "Integrate with ERP" (6c0d205a)
    มาจากส่วนหน้าที่ — เก็บเฉพาะเทคโนโลยีที่ประกาศยกเป็นตัวอย่างหรือตัวเลือก."""
    r = to_requirement(ex(
        item("low-latency", kind="knowledge_field", section="duties"),
        item("engineering techniques", kind="method", section="duties"),
        item("AI Chatbots", section="duties"),
        item("ERP", section="duties"),
        item("LangChain", necessity="example", section="duties", group="llm fw"),
        item("GPT", necessity="one_of", section="duties", group="llm"),
    ))
    assert r.required_skills == [] and r.preferred_skills == ["LangChain", "GPT"]


def test_unsectioned_line_with_a_duty_becomes_duties():
    """วัดจริง 7b44445d: คำกริยาติด duties แต่ ML/DL ในบรรทัดเดียวกันติด unsectioned → ข้อบังคับ 13 ตัว."""
    line = "Develop AI services and projects using ML, DL, and GenAI technologies."
    r = to_requirement(ex(
        item("AI services", kind="duty", section="duties", line=line),
        item("ML", kind="knowledge_field", section="unsectioned", line=line),
        item("LangChain", necessity="example", section="unsectioned", line="Integrate LLMs using frameworks such as LangChain"),
        item("Integrate LLMs", kind="duty", section="unsectioned", line="Integrate LLMs using frameworks such as LangChain"),
    ))
    assert r.required_skills == [] and r.preferred_skills == ["LangChain"]


def test_qualification_line_is_never_pulled_into_duties():
    line = "Experience building REST APIs with Python"
    r = to_requirement(ex(
        item("building REST APIs", kind="duty", section="qualifications", line=line),
        item("Python", section="qualifications", line=line),
    ))
    assert r.required_skills == ["Python"]


def test_unsectioned_line_without_duties_stays_required():
    line = "Looking for a Frontend Developer with React and TypeScript."
    r = to_requirement(ex(item("React", section="unsectioned", line=line),
                          item("TypeScript", section="unsectioned", line=line)))
    assert r.required_skills == ["React", "TypeScript"]


# ---------- ตาข่าย "or/หรือ" เมื่อ LLM ติดป้าย must ผิด ----------


def test_or_line_labelled_must_is_demoted():
    """วัดจริง: "AI, Machine Learning, or Data Science" ถูกติดป้าย must ทุกตัว."""
    line = "At least 2-5 years of experience in AI, Machine Learning, or Data Science"
    r = to_requirement(ex(*(item(n, kind="knowledge_field", line=line)
                            for n in ("AI", "Machine Learning", "Data Science")), item("Python")))
    assert r.required_skills == ["AI | Machine Learning | Data Science", "Python"]
    assert r.preferred_skills == []


def test_thai_or_line_is_demoted():
    line = "ใช้ cloud อย่างใดอย่างหนึ่ง: AWS, Azure หรือ GCP"
    r = to_requirement(ex(*(item(n, line=line) for n in ("AWS", "Azure", "GCP"))))
    assert r.required_skills == ["AWS | Azure | GCP"] and r.preferred_skills == []


def test_or_in_education_clause_does_not_demote_single_skill():
    """มีคำว่าหรือ แต่มีทักษะแค่ตัวเดียวในท่อนนั้น — ไม่มีอะไรให้เลือกระหว่างกัน."""
    line = "Python required; ปริญญาตรีสาขาคอมพิวเตอร์หรือสาขาที่เกี่ยวข้อง"
    r = to_requirement(ex(item("Python", line=line)))
    assert r.required_skills == ["Python"]


def test_or_only_affects_its_own_clause():
    line = "Must know Python and FastAPI. Docker or Podman is fine"
    r = to_requirement(ex(*(item(n, line=line) for n in ("Python", "FastAPI", "Docker", "Podman"))))
    assert r.required_skills == ["Python", "FastAPI", "Docker | Podman"]
    assert r.preferred_skills == []


def test_and_before_an_or_group_keeps_the_must_item():
    line = "Python and PyTorch, TensorFlow, or Hugging Face"
    r = to_requirement(ex(*(item(n, line=line) for n in ("Python", "PyTorch", "TensorFlow", "Hugging Face"))))
    assert r.required_skills == ["Python", "PyTorch | TensorFlow | Hugging Face"]
    assert r.preferred_skills == []


def test_thai_and_splits_clauses_but_and_or_does_not():
    th = "ใช้ Git และ Docker หรือ Podman"
    r = to_requirement(ex(*(item(n, line=th) for n in ("Git", "Docker", "Podman"))))
    assert r.required_skills == ["Git", "Docker | Podman"] and r.preferred_skills == []
    en = "Java and/or Kotlin"
    r = to_requirement(ex(item("Java", line=en), item("Kotlin", line=en)))
    assert r.required_skills == ["Java | Kotlin"] and r.preferred_skills == []


def test_or_check_does_not_split_dotted_names():
    """จุดใน "Next.js" ไม่ใช่จุดจบประโยค."""
    line = "React or Next.js"
    r = to_requirement(ex(item("React", line=line), item("Next.js", line=line)))
    assert r.required_skills == ["React | Next.js"] and r.preferred_skills == []


def test_or_check_ignores_skills_from_other_lines_and_word_fragments():
    """"SQL" จาก "Python and SQL" ต้องไม่ถูกลากไปเพราะอีกบรรทัดเขียน "PostgreSQL or MySQL"
    และ "Go" ต้องไม่ถูกนับว่าอยู่ใน "Google"."""
    r = to_requirement(ex(
        item("Python", line="Python and SQL"), item("SQL", line="Python and SQL"),
        item("Go", line="Go, plus Google Cloud or AWS"),
        item("PostgreSQL", line="PostgreSQL or MySQL"), item("MySQL", line="PostgreSQL or MySQL"),
    ))
    assert r.required_skills == ["Python", "SQL", "Go", "PostgreSQL | MySQL"]
    assert r.preferred_skills == []


def test_generic_suffix_is_trimmed_so_resumes_can_match():
    """ประกาศ JobsDB จริง: "Python Programming" ไม่มีวันตรงกับเรซูเม่ที่เขียน "Python"."""
    r = to_requirement(ex(
        item("Python Programming"),
        item("AI technology", kind="knowledge_field"),
        item("Generative AI Development", kind="knowledge_field", necessity="one_of"),
        item("Programming"),
    ))
    assert r.required_skills == ["Python", "AI", "Programming"]
    assert r.preferred_skills == ["Generative AI"]


@pytest.mark.parametrize("name", ["Web Development", "Mobile Development", "Software Development",
                                  "Full Stack Development", "Data Technology"])
def test_trim_never_leaves_a_broad_word(name):
    """"Web Development" → "Web" จะไปตรงกับ "Web Scraping" — ต้องคงชื่อเต็มไว้."""
    assert to_requirement(ex(item(name))).required_skills == [name]


def test_trim_only_applies_to_skill_kinds():
    r = to_requirement(ex(item("Rust Language", kind="method"), item("Java Skills", kind="technology")))
    assert r.required_skills == ["Rust", "Java"]


# ---------- บรรทัดต้นฉบับ: ไม่พึ่งให้ LLM ยกมาตรงตัวอักษร ----------


def test_or_check_uses_the_real_jd_line_when_quote_is_partial():
    """LLM ยกมาแค่ครึ่งบรรทัด (ไม่มีคำว่า or) — ต้องไปหาบรรทัดจริงในประกาศ."""
    jd = "Required Skills\n- PyTorch, TensorFlow, or Hugging Face\n- Python and SQL"
    r = to_requirement(ex(
        item("PyTorch", line="PyTorch, TensorFlow"),
        item("TensorFlow", line="- PyTorch, TensorFlow,"),
        item("Python", line="Python and SQL"),
    ), jd)
    assert r.required_skills == ["PyTorch | TensorFlow", "Python"]
    assert r.preferred_skills == []


def test_duty_line_grouping_ignores_bullets_case_and_spacing():
    """คำกริยาถูกติด duties แต่ LLM ยก ML มาต่างกันนิดหน่อย — ต้องยังนับเป็นบรรทัดเดียวกัน."""
    jd = "* Develop AI services using ML and GenAI technologies."
    r = to_requirement(ex(
        item("AI services", kind="duty", section="duties",
             line="* Develop AI services using ML and GenAI technologies."),
        item("ML", kind="knowledge_field", section="unsectioned", line="develop AI services  using ML"),
    ), jd)
    assert r.required_skills == [] and r.preferred_skills == []


def test_line_keys_fall_back_to_quote_without_raw_jd():
    """ไม่มี raw_jd (เช่น replay ป้ายเก่า) — ใช้ source_line ที่ normalize แล้ว."""
    r = to_requirement(ex(item("React", line="  React OR Vue "), item("Vue", line="react or vue")))
    assert r.required_skills == ["React | Vue"] and r.preferred_skills == []


# ---------- หัวข้อย่อย "Nice-to-Have / แต้มต่อ" ในประกาศ (โค้ดอ่านเอง ไม่พึ่งป้าย) ----------
# เคสจริง Junior Web Developer 2026-09-22: หัวข้ออยู่คนละบรรทัดกับทักษะ LLM จึงติด one_of/must
# ให้ทักษะใต้ Nice-to-Have แล้วมันหลุดไปฝั่งต้องมีทั้งหมด

_WEB_JD = """หน้าที่ความรับผิดชอบ (Responsibilities)
เชื่อมต่อ API (RESTful API) ระหว่าง Front-end และ Back-end
Must-Have (ทักษะจำเป็น):
Core Web: HTML5, CSS3
Version Control: Git, GitHub / GitLab
Nice-to-Have (ทักษะสอดคล้อง/แต้มต่อ):
Front-end Framework: React.js, Vue.js, หรือ Next.js
Tooling & Build: npm / yarn, VS Code, Postman
🤝 Soft Skills
Communication: Git workflow"""


def test_skills_under_nice_to_have_heading_go_to_preferred_whatever_the_label():
    core, vcs = "Core Web: HTML5, CSS3", "Version Control: Git, GitHub / GitLab"
    fe, tools = "Front-end Framework: React.js, Vue.js, หรือ Next.js", "Tooling & Build: npm / yarn, VS Code, Postman"
    r = to_requirement(ex(
        item("HTML5", line=core), item("CSS3", line=core),
        item("Git", line=vcs),
        *(item(n, necessity="one_of", group="fe", line=fe) for n in ("React.js", "Vue.js", "Next.js")),
        *(item(n, necessity="one_of", group="pm", line=tools) for n in ("npm", "yarn")),
        item("VS Code", line=tools), item("Postman", line=tools),  # LLM ติด must ทั้งที่อยู่ใต้ Nice-to-Have
    ), _WEB_JD)
    assert r.required_skills == ["HTML5", "CSS3", "Git"]
    assert r.preferred_skills == ["React.js | Vue.js | Next.js", "npm | yarn", "VS Code", "Postman"]


def test_next_heading_closes_the_preferred_range():
    """"🤝 Soft Skills" ปิดช่วง — ทักษะหลังจากนั้นไม่ถูกลากเป็นอยากได้."""
    r = to_requirement(ex(item("Git", line="Communication: Git workflow")), _WEB_JD)
    assert r.required_skills == ["Git"]


def test_one_line_is_a_plus_does_not_open_a_range():
    jd = "Qualifications:\nDocker is a plus\nPython, SQL"
    r = to_requirement(ex(
        item("Docker", necessity="plus", line="Docker is a plus"),
        item("Python", line="Python, SQL"), item("SQL", line="Python, SQL"),
    ), jd)
    assert r.required_skills == ["Python", "SQL"]
    assert r.preferred_skills == ["Docker"]


def test_inline_nice_to_have_label_only_affects_its_own_line():
    jd = "Requirements:\nNice to have: Docker, Kubernetes\nPython"
    line = "Nice to have: Docker, Kubernetes"
    r = to_requirement(ex(item("Docker", line=line), item("Kubernetes", line=line), item("Python")), jd)
    assert r.required_skills == ["Python"]
    assert r.preferred_skills == ["Docker", "Kubernetes"]


def test_preferred_qualifications_heading_counts_as_preferred():
    jd = "Required Qualifications:\n- Python\nPreferred Qualifications:\n- Docker"
    r = to_requirement(ex(item("Python", line="- Python"), item("Docker", line="- Docker")), jd)
    assert r.required_skills == ["Python"]
    assert r.preferred_skills == ["Docker"]


def test_thai_heading_markers():
    jd = "คุณสมบัติ\nPython\nจะพิจารณาเป็นพิเศษ:\nDocker"
    r = to_requirement(ex(item("Python"), item("Docker")), jd)
    assert r.required_skills == ["Python"] and r.preferred_skills == ["Docker"]


def test_lists_pasted_on_one_line_split_at_labels():
    """รายการทักษะถูกวางต่อกันบรรทัดเดียว — "หรือ" ตัวเดียวเคยดูดทั้งบรรทัดเป็นกลุ่มเดียว 16 ตัว.

    หัวข้อย่อย ("Responsive Design:") เป็นตัวเลือกร่วมกับท่อน "ถัดไป" ไม่ใช่ท่อนก่อนหน้า
    """
    line = ("Must-Have (ทักษะจำเป็น): Core Web: HTML5, CSS3 Responsive Design: Bootstrap, "
            "หรือ Tailwind CSS Version Control: Git, GitHub")
    names = ["HTML5", "CSS3", "Responsive Design", "Bootstrap", "Tailwind CSS", "Version Control", "Git", "GitHub"]
    r = to_requirement(ex(*(item(n, kind="method" if " " in n and n != "Tailwind CSS" else "technology", line=line)
                            for n in names)), line)
    # Version Control เป็นหัวข้อของ "Git, GitHub" จึงถูกตัด (ดู test_heading_* ด้านล่าง)
    assert r.required_skills == [
        "HTML5", "CSS3", "Responsive Design | Bootstrap | Tailwind CSS", "Git", "GitHub",
    ]


def test_label_on_its_own_line_still_groups_with_its_options():
    """ประกาศปกติ (หนึ่งรายการต่อบรรทัด) — หัวข้อยังรวมกับตัวเลือกของมันเหมือนเดิม."""
    line = "Responsive Design: Bootstrap, Tailwind CSS, หรือ CSS Flexbox/Grid"
    r = to_requirement(ex(
        item("Responsive Design", kind="method", line=line),
        *(item(n, necessity="one_of", group="css", line=line)
          for n in ("Bootstrap", "Tailwind CSS", "CSS Flexbox/Grid")),
    ), line)
    assert r.required_skills == ["Responsive Design | Bootstrap | Tailwind CSS | CSS Flexbox/Grid"]


# ---------- ชื่อหัวข้อย่อยที่นำหน้ารายการทักษะ ไม่ใช่ทักษะ ----------


def test_heading_before_a_skill_list_is_dropped():
    vcs = "Version Control: Git, GitHub / GitLab"
    api = "API Handling: RESTful API, JSON"
    r = to_requirement(ex(
        item("Version Control", kind="method", line=vcs), item("Git", line=vcs),
        *(item(n, necessity="one_of", group="host", line=vcs) for n in ("GitHub", "GitLab")),
        item("API Handling", kind="method", line=api), item("RESTful API", line=api), item("JSON", line=api),
    ), f"{vcs}\n{api}")
    assert r.required_skills == ["Git", "GitHub | GitLab", "RESTful API", "JSON"]


def test_skill_followed_by_a_level_is_kept():
    """"Python: 3+ years" — Python คือทักษะจริง ไม่มีทักษะอื่นต่อท้าย ต้องไม่ถูกตัด."""
    r = to_requirement(ex(
        item("Python", line="Python: 3+ years"), item("SQL", line="SQL: ระดับดี"),
    ), "Python: 3+ years\nSQL: ระดับดี")
    assert r.required_skills == ["Python", "SQL"]


def test_heading_inside_an_or_group_stays_as_an_option():
    line = "Responsive Design: Bootstrap, Tailwind CSS, หรือ CSS Flexbox/Grid"
    r = to_requirement(ex(
        item("Responsive Design", kind="method", line=line),
        *(item(n, necessity="one_of", group="css", line=line)
          for n in ("Bootstrap", "Tailwind CSS", "CSS Flexbox/Grid")),
    ), line)
    assert r.required_skills == ["Responsive Design | Bootstrap | Tailwind CSS | CSS Flexbox/Grid"]


def test_heading_on_its_own_line_is_kept():
    """หัวข้อบรรทัดเดี่ยว รายการอยู่บรรทัดถัดไป — ยังไม่ตัด (ฝั่งปลอดภัย, ข้อจำกัดที่รู้อยู่)."""
    r = to_requirement(ex(
        item("Version Control", kind="method", line="Version Control:"), item("Git", line="- Git"),
    ), "Version Control:\n- Git")
    assert r.required_skills == ["Version Control", "Git"]


def test_heading_of_other_line_does_not_count():
    """ต้องมีทักษะอื่นจากบรรทัดเดียวกันต่อท้าย — ชื่อที่ตรงกันจากบรรทัดอื่นไม่นับ."""
    r = to_requirement(ex(
        item("Docker", line="Docker: containerization"), item("Kubernetes", line="Kubernetes"),
    ), "Docker: containerization\nKubernetes")
    assert r.required_skills == ["Docker", "Kubernetes"]


def test_blank_and_role_names_are_filtered():
    r = to_requirement(ex(item("  "), item("data scientists"), item(" Go ")))
    assert r.required_skills == ["Go"]


def test_scalar_fields_pass_through():
    e = JDExtraction(job_title="AI Engineer", min_experience_years=-1, education="ป.โท", items=[])
    r = to_requirement(e)
    assert (r.job_title, r.min_experience_years, r.education) == ("AI Engineer", 0, "ป.โท")


# ---------- สัญญากับ LLM ----------


def test_prompt_formats_without_stray_braces():
    text = jd_analyzer.PROMPT.format(raw_jd="JD_MARKER")
    assert "JD_MARKER" in text
    assert "{" not in text and "}" not in text


def test_analyze_jd_asks_for_labels_and_returns_requirement_shape():
    fake = ex(item("Python"), item("PyTorch", necessity="one_of", group="ml"), title="AI Engineer")
    with patch.object(jd_analyzer, "structured_invoke", return_value=fake) as inv:
        out = jd_analyzer.analyze_jd({"raw_jd": "Python required; PyTorch or TensorFlow", "analyzed_jd": None})
    inv.assert_called_once()
    prompt, model = inv.call_args.args
    assert model is JDExtraction
    assert "PyTorch or TensorFlow" in prompt
    # state ของกราฟยังเป็นรูป JobRequirement เดิม — checkpoint/matcher ไม่ต้องรู้เรื่องป้าย
    assert out == {"analyzed_jd": JobRequirement(
        job_title="AI Engineer", min_experience_years=2, education="ป.ตรี",
        required_skills=["Python"], preferred_skills=["PyTorch"]).model_dump()}


def test_analyze_jd_skips_llm_when_already_analyzed():
    with patch.object(jd_analyzer, "structured_invoke") as inv:
        assert jd_analyzer.analyze_jd({"raw_jd": "x", "analyzed_jd": {"job_title": "x"}}) == {}
    inv.assert_not_called()


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: "admin-test"
    yield TestClient(app)
    app.dependency_overrides.clear()


def _delete_job(jid):
    with get_conn() as conn:
        conn.execute("DELETE FROM jobs WHERE id = %s", (jid,))
        conn.commit()


def test_create_job_stores_labels_and_sorted_criteria(client):
    fake = ex(item("Python"), item("AWS", necessity="one_of", group="cloud"),
              item("monitoring", kind="duty", section="duties"), title="ทดสอบ jd_extraction — ลบได้")
    with patch.object(jd_analyzer, "structured_invoke", return_value=fake):
        res = client.post("/api/v1/jobs", json={"raw_text": "Python; AWS or GCP; monitoring"})
    assert res.status_code == 201, res.text
    jid = res.json()["id"]
    try:
        assert res.json()["parsed_criteria"]["required_skills"] == ["Python"]
        assert res.json()["parsed_criteria"]["preferred_skills"] == ["AWS"]
        with get_conn() as conn:
            row = conn.execute("SELECT jd_extraction FROM jobs WHERE id = %s", (jid,)).fetchone()
        stored = row["jd_extraction"]["items"]
        # ป้ายดิบครบทุกคำ รวมคำที่ถูกตัดทิ้ง — ทางแก้ข้อ 3 ต้องใช้ one_of/group
        assert [(i["name"], i["kind"], i["necessity"], i["group"]) for i in stored] == [
            ("Python", "technology", "must", ""),
            ("AWS", "technology", "one_of", "cloud"),
            ("monitoring", "duty", "must", ""),
        ]
    finally:
        _delete_job(jid)


def test_create_job_survives_llm_failure(client):
    with patch.object(jd_analyzer, "structured_invoke", side_effect=RuntimeError("quota")):
        res = client.post("/api/v1/jobs", json={"raw_text": "ทดสอบ LLM ล้ม — ลบได้\nPython"})
    assert res.status_code == 201
    jid = res.json()["id"]
    try:
        assert res.json()["parsed_criteria"] is None
        with get_conn() as conn:
            row = conn.execute("SELECT jd_extraction FROM jobs WHERE id = %s", (jid,)).fetchone()
        assert row["jd_extraction"] is None
    finally:
        _delete_job(jid)


# ---------- คำเตือนเกณฑ์บน JobOut ----------


def _job(criteria):
    return JobOut(
        id=uuid4(),
        title="t",
        raw_text="r",
        parsed_criteria=criteria,
        created_at=datetime.now(timezone.utc),
    )


def test_job_warnings_empty_without_criteria():
    assert _job(None).criteria_warnings == []


def test_job_warns_when_only_preferred():
    job = _job({"required_skills": [], "preferred_skills": ["PyTorch", "TensorFlow"]})
    assert len(job.criteria_warnings) == 1
    assert "มีแค่ทักษะที่อยากได้" in job.criteria_warnings[0]
    # ต้องออกไปกับ response ด้วย ไม่ใช่แค่ property ใน Python
    assert job.model_dump(mode="json")["criteria_warnings"] == job.criteria_warnings


def test_job_warns_when_required_bloated():
    job = _job({"required_skills": [f"Skill{i}" for i in range(20)], "preferred_skills": []})
    assert any("20 ข้อ" in w for w in job.criteria_warnings)


def test_job_no_warning_for_healthy_criteria():
    job = _job({"required_skills": ["Python", "FastAPI"], "preferred_skills": ["Docker"]})
    assert job.criteria_warnings == []
