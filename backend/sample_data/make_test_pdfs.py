"""สร้าง PDF resume ตัวอย่างสำหรับทดสอบ e2e (ภาษาอังกฤษ เลี่ยงปัญหาฟอนต์ไทยใน PDF).

ไฟล์ .pdf ที่ได้ commit ไว้แล้วใน sample_data/ — รันสคริปต์นี้เฉพาะเมื่อต้องการสร้างใหม่:
    docker compose run --rm --no-deps backend sh -c "pip install -q reportlab && python sample_data/make_test_pdfs.py"
(reportlab ไม่ได้อยู่ใน requirements.txt เพราะใช้แค่ตอนสร้างไฟล์ทดสอบ)

ออกแบบให้ตกคนละแบนด์เมื่อเทียบกับ JD ที่ใช้ทดสอบ:
  required = Python, FastAPI, PostgreSQL | preferred = Docker, LangGraph
  strong: ครบทุกอย่าง            -> 60*(3/3) + 40*(2/2) = 100  (auto)
  mid   : ขาด PostgreSQL, LangGraph -> 60*(2/3) + 40*(1/2) = 60   (รอ HR)
  weak  : ไม่ตรงเลย               -> 0                            (reject)
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent
OUT.mkdir(exist_ok=True)

RESUMES = {
    "strong_somchai.pdf": [
        "Somchai Jaidee",
        "Email: somchai@example.com",
        "",
        "Summary: Senior Backend Engineer with 6 years of experience.",
        "",
        "Skills: Python, FastAPI, PostgreSQL, Docker, LangGraph, Redis",
        "",
        "Experience:",
        "- 2019-2025 Backend Engineer, ACME Co.",
        "  Built REST APIs with Python and FastAPI on PostgreSQL.",
        "  Deployed services with Docker. Built LLM pipelines with LangGraph.",
        "",
        "Education: B.Sc. Computer Science, Example University",
    ],
    "mid_suda.pdf": [
        "Suda Rakdee",
        "Email: suda@example.com",
        "",
        "Summary: Backend developer with 3 years of experience.",
        "",
        "Skills: Python, FastAPI, Docker, MongoDB",
        "",
        "Experience:",
        "- 2022-2025 Developer, Beta Ltd.",
        "  Built internal APIs using Python and FastAPI.",
        "  Containerized apps with Docker. Used MongoDB for storage.",
        "",
        "Education: B.Sc. Information Technology, Example University",
    ],
    "weak_anan.pdf": [
        "Anan Sukjai",
        "Email: anan@example.com",
        "",
        "Summary: Graphic designer with 4 years of experience.",
        "",
        "Skills: Photoshop, Illustrator, Figma, HTML, CSS",
        "",
        "Experience:",
        "- 2021-2025 Graphic Designer, Gamma Studio.",
        "  Designed marketing materials and social media assets.",
        "",
        "Education: B.A. Fine Arts, Example University",
    ],
}

for filename, lines in RESUMES.items():
    path = OUT / filename
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 11)
    y = 800
    for line in lines:
        c.drawString(50, y, line)
        y -= 18
    c.save()
    print("created:", path)
