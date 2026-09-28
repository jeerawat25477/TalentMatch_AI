"""สร้างเรซูเม่ PDF สำหรับทดสอบ/สาธิต — บุคคลและบริษัทสมมติทั้งหมด (อีเมล @example.com).

รันบนเครื่อง Windows (ไม่ใช่ในคอนเทนเนอร์): เขียน HTML แล้วสั่ง Microsoft Edge แบบ headless พิมพ์เป็น PDF
    python demo_resumes/generate.py

ทำไมใช้ Edge ไม่ใช่ PyMuPDF: PyMuPDF เขียนวรรณยุกต์ที่อยู่บนสระอี/อื (เช่น "ที่") เป็นรหัสผิด
ตอนอ่านกลับได้ "ทีŕ" · Edge เขียน ToUnicode ถูก ไฟล์เล็กกว่า (~20 KB) และเหมือน PDF ที่คนทั่วไปส่งมา

ไฟล์ edge_01_scanned_image_only.pdf ต้องแปลงเป็นรูปต่อในคอนเทนเนอร์ (ดู README.md)
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "pdf"
HTML_DIR = HERE / "html"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

CSS = """
@page { size: A4; margin: 14mm 15mm; }
* { font-family: 'Leelawadee UI', Tahoma, sans-serif; font-size: 9.5pt; line-height: 1.4; color: #222; }
h1 { font-size: 19pt; margin: 0 0 2px 0; color: #0b3d91; }
h2 { font-size: 11pt; margin: 11px 0 3px 0; color: #0b3d91; border-bottom: 1px solid #0b3d91; }
.sub { font-size: 10.5pt; margin: 0 0 4px 0; }
.muted { color: #555; }
p { margin: 2px 0; }
ul { margin: 2px 0 2px 18px; padding: 0; }
li { margin: 1px 0; }
.job { font-weight: bold; margin-top: 6px; }
td { vertical-align: top; }
"""


def save(name, html, scanned=False):
    """เขียน HTML แล้วให้ Edge พิมพ์เป็น PDF (scanned=True ไว้แปลงเป็นรูปต่อ ดู README)."""
    OUT.mkdir(parents=True, exist_ok=True)
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    src = HTML_DIR / name.replace(".pdf", ".html")
    src.write_text(f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{html}</body></html>",
                   encoding="utf-8")
    dst = OUT / name
    subprocess.run([EDGE, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={dst}", src.as_uri()], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("wrote", dst.name, "(scanned: convert in container)" if scanned else "")


def header(name, title, contact):
    return f"<h1>{name}</h1><p class='sub'>{title}</p><p class='muted'>{contact}</p>"


def section(title, body):
    return f"<h2>{title}</h2>{body}"


def ul(items):
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def job(title, org, period, bullets):
    return f"<p class='job'>{title} — {org} <span class='muted'>({period})</span></p>" + ul(bullets)


# ======================= AI Engineer =======================

save("ai_01_strong_fit_EN.pdf", header(
    "Natthapong Srisuk", "AI Engineer · 4 years experience",
    "Bangkok, Thailand · natthapong.s@example.com · 080-000-0101 · linkedin.com/in/example-natthapong",
) + section("Summary", "<p>AI Engineer with 4 years building production LLM and machine learning systems. "
    "Shipped RAG assistants and AI agents used by 3,000+ employees, and fine-tuned open-source models "
    "for Thai-language document tasks. Comfortable owning the full lifecycle from data pipeline to "
    "deployment on Azure and Kubernetes.</p>")
+ section("Experience",
    job("AI Engineer", "Siam Insight Analytics Co., Ltd.", "Mar 2024 – Present", [
        "Built an internal RAG assistant (LangChain + Azure OpenAI + pgvector) answering HR and IT "
        "policy questions; cut ticket volume by 32%.",
        "Designed multi-step AI agents with LangGraph for invoice checking; 91% of cases resolved "
        "without human review.",
        "Fine-tuned a Llama-based model with LoRA on 40k Thai contract clauses (Hugging Face, PyTorch); "
        "F1 improved from 0.71 to 0.86.",
        "Containerised services with Docker and deployed to AKS (Kubernetes); set up CI/CD with GitHub "
        "Actions and automated evaluation of prompts.",
    ]) +
    job("Machine Learning Engineer", "Chaophraya Retail Tech Co., Ltd.", "Jun 2022 – Feb 2024", [
        "Trained demand-forecasting models with scikit-learn and XGBoost for 1,200 SKUs; MAPE down 18%.",
        "Wrote SQL feature pipelines on PostgreSQL and BigQuery; scheduled with Airflow.",
        "Introduced prompt engineering guidelines and an OpenAI API wrapper shared by 4 product teams.",
    ]))
+ section("Education", "<p><b>B.Eng. Computer Engineering</b> — Chulalongkorn University, 2018–2022 · GPA 3.42</p>")
+ section("Skills", ul([
    "<b>Languages:</b> Python, SQL, TypeScript",
    "<b>ML / DL:</b> PyTorch, TensorFlow, scikit-learn, Hugging Face Transformers",
    "<b>LLM:</b> OpenAI API, Azure OpenAI, Claude API, LangChain, LangGraph, LlamaIndex, RAG, "
    "Prompt Engineering, Fine-tuning (LoRA), AI Agents",
    "<b>Vector DB:</b> pgvector, ChromaDB, FAISS",
    "<b>Cloud / DevOps:</b> Microsoft Azure, AWS, Docker, Kubernetes, Git, CI/CD (GitHub Actions)",
]))
+ section("Certifications", ul(["Microsoft Certified: Azure AI Engineer Associate (2024)",
                                "DeepLearning.AI — LangChain for LLM Application Development (2023)"]))
+ section("Languages", "<p>Thai (native) · English (TOEIC 865)</p>"))


save("ai_02_data_scientist_partial_TH.pdf", header(
    "พิมพ์ชนก วงศ์ประเสริฐ", "Data Scientist · ประสบการณ์ 3 ปี",
    "นนทบุรี · pimchanok.w@example.com · 080-000-0102",
) + section("เป้าหมายในการทำงาน", "<p>ต้องการต่อยอดจากงาน Data Science ไปสู่งาน AI Engineer "
    "โดยเฉพาะด้าน Generative AI ที่เริ่มศึกษาด้วยตัวเองมา 6 เดือน</p>")
+ section("ประสบการณ์ทำงาน",
    job("Data Scientist", "บริษัท ไทยเครดิต อนาไลติกส์ จำกัด", "ม.ค. 2566 – ปัจจุบัน", [
        "สร้างโมเดล credit scoring ด้วย Python, scikit-learn และ XGBoost ใช้กับลูกค้า 200,000 ราย",
        "เขียน SQL ดึงและเตรียมข้อมูลจาก data warehouse บน AWS (Redshift, S3)",
        "ทำ dashboard ติดตามประสิทธิภาพโมเดลด้วย Power BI นำเสนอผู้บริหารรายเดือน",
        "ทดลองสร้างโมเดลจำแนกข้อความร้องเรียนลูกค้าด้วย TensorFlow ความแม่นยำ 84%",
    ]) +
    job("Data Analyst", "บริษัท สยามโลจิสติกส์ ดิจิทัล จำกัด", "มิ.ย. 2564 – ธ.ค. 2565", [
        "วิเคราะห์เส้นทางขนส่งด้วย Python (pandas) ลดต้นทุนค่าขนส่งได้ 7%",
        "ดูแลรายงานอัตโนมัติด้วย SQL และ Excel VBA",
    ]))
+ section("การศึกษา", "<p><b>วิทยาศาสตรบัณฑิต สาขาสถิติ</b> — มหาวิทยาลัยเกษตรศาสตร์ ปี 2560–2564 เกรดเฉลี่ย 3.28</p>")
+ section("ทักษะ", ul([
    "Python, SQL, R", "Machine Learning, scikit-learn, TensorFlow, XGBoost",
    "AWS (S3, Redshift, SageMaker เบื้องต้น), Git", "Power BI, Excel",
    "กำลังศึกษา: ChatGPT / OpenAI API, Prompt Engineering",
]))
+ section("ภาษา", "<p>ไทย (ภาษาแม่) · อังกฤษ (ดี — TOEIC 740)</p>"))


save("ai_03_new_grad_personal_info_TH.pdf", header(
    "ธนกฤต ใจดี", "นักศึกษาจบใหม่ · สมัครตำแหน่ง AI Engineer (Junior)",
    "ขอนแก่น · thanakrit.j@example.com · 080-000-0103",
) + section("ข้อมูลส่วนตัว", ul([
    "เพศ: ชาย · อายุ: 22 ปี · วันเกิด: 14 กุมภาพันธ์ 2547",
    "สัญชาติ: ไทย · ศาสนา: พุทธ · สถานภาพ: โสด",
    "สถานะทางทหาร: ได้รับการยกเว้น (เรียน รด. ครบ 3 ปี)",
]))
+ section("การศึกษา", "<p><b>วิศวกรรมศาสตรบัณฑิต สาขาวิศวกรรมคอมพิวเตอร์</b> — มหาวิทยาลัยขอนแก่น "
    "ปี 2565–2569 เกรดเฉลี่ย 3.61 (เกียรตินิยมอันดับ 2)</p>")
+ section("โปรเจกต์", ul([
    "<b>ปริญญานิพนธ์: แชตบอตตอบคำถามระเบียบมหาวิทยาลัย</b> — RAG ด้วย LangChain, OpenAI API และ "
    "ChromaDB ตอบถูก 82% จากชุดคำถาม 300 ข้อ",
    "<b>จำแนกโรคใบข้าวจากรูปภาพ</b> — PyTorch (ResNet-50) ความแม่นยำ 93% นำเสนองาน NSC 2025",
    "<b>สรุปข่าวภาษาไทย</b> — fine-tuning โมเดลจาก Hugging Face บน Google Colab",
]))
+ section("ประสบการณ์ฝึกงาน",
    job("นักศึกษาฝึกงาน AI", "บริษัท อีสาน สมาร์ทซิตี้ จำกัด", "มิ.ย. – ส.ค. 2568", [
        "ช่วยทำระบบนับรถจากกล้อง CCTV ด้วย Python และ OpenCV",
        "เขียน SQL สรุปข้อมูลการจราจรรายวัน และใช้ Git ทำงานร่วมกับทีม",
    ]))
+ section("ทักษะ", ul([
    "Python, SQL, C++", "PyTorch, Hugging Face, Machine Learning, Deep Learning",
    "LangChain, OpenAI API, Prompt Engineering, RAG", "Git, Linux, Google Colab",
]))
+ section("กิจกรรม", ul(["ประธานชมรมหุ่นยนต์ ปี 2567", "จิตอาสาสอนเขียนโปรแกรมให้นักเรียนมัธยม"]))
+ section("ภาษา", "<p>ไทย (ภาษาแม่) · อังกฤษ (พอใช้)</p>"))


save("ai_04_backend_career_switch_EN.pdf", header(
    "Kittipat Rattanakorn", "Senior Backend Developer → looking to move into AI",
    "Bangkok · kittipat.r@example.com · 080-000-0104 · github.com/example-kittipat",
) + section("Summary", "<p>Backend developer with 6 years of Java and Spring Boot experience in fintech. "
    "Strong in cloud infrastructure and delivery pipelines. Recently used ChatGPT and GitHub Copilot "
    "daily and built a small internal chatbot prototype; now looking for an AI role.</p>")
+ section("Experience",
    job("Senior Backend Developer", "Krungthep Pay Co., Ltd.", "2021 – Present", [
        "Led the payment gateway team (5 devs); 2,000 transactions/second on Kubernetes (EKS).",
        "Migrated 30 services to Docker and GitHub Actions CI/CD; release time cut from 1 day to 40 min.",
        "Prototype: FAQ chatbot calling the OpenAI API from a Spring Boot service (internal demo only).",
    ]) +
    job("Backend Developer", "Lanna Soft Co., Ltd.", "2019 – 2021", [
        "Built REST APIs with Java, Spring Boot and PostgreSQL for an e-procurement system.",
        "Wrote complex SQL reports and tuned slow queries (p95 from 3.2s to 400ms).",
    ]))
+ section("Education", "<p><b>B.Sc. Computer Science</b> — Chiang Mai University, 2015–2019</p>")
+ section("Skills", ul([
    "Java, Kotlin, Spring Boot, SQL, PostgreSQL, Redis, Kafka",
    "AWS (EKS, RDS, S3), Docker, Kubernetes, Git, CI/CD, Terraform",
    "AI tools: ChatGPT, GitHub Copilot, OpenAI API (basic)",
]))
+ section("Certifications", ul(["AWS Certified Solutions Architect – Associate (2023)"])))


# 2 คอลัมน์แบบเทมเพลต Canva — ทดสอบลำดับข้อความตอนอ่าน PDF
save("ai_05_two_column_canva_style_EN.pdf",
    "<table width='100%'><tr>"
    "<td width='34%' style='background:#eef3fb;padding:8px'>"
    "<h1>Supansa<br/>Thongdee</h1><p class='sub'>ML Engineer</p>"
    + section("Contact", "<p>supansa.t@example.com<br/>080-000-0105<br/>Chonburi</p>")
    + section("Skills", ul(["Python", "SQL", "TensorFlow", "Keras", "Deep Learning", "Computer Vision",
                           "Google Cloud Platform", "Vertex AI", "Docker", "Git"]))
    + section("Languages", "<p>Thai, English (IELTS 6.5)</p>")
    + "</td><td width='66%' style='padding:8px 8px 8px 14px'>"
    + section("Profile", "<p>ML engineer focused on computer vision for manufacturing quality control. "
        "Deployed defect-detection models to 6 factory lines.</p>")
    + section("Experience",
        job("Machine Learning Engineer", "Eastern Smart Factory Co., Ltd.", "2023 – Present", [
            "Built defect detection with TensorFlow and Keras; false rejects down 40%.",
            "Trained and served models on Google Cloud Platform (Vertex AI) with Docker.",
        ]) + job("Research Assistant", "Burapha University", "2022 – 2023", [
            "Deep learning experiments for fruit grading from images.",
        ]))
    + section("Education", "<p>M.Sc. Data Science — Burapha University, 2021–2023</p>")
    + "</td></tr></table>")


# ======================= ฝ่ายอื่น =======================

save("mkt_01_digital_marketing_fit_TH.pdf", header(
    "ณัฐธิดา แสงทอง", "Digital Marketing Executive · ประสบการณ์ 3 ปี",
    "กรุงเทพฯ · nattida.s@example.com · 080-000-0201",
) + section("ประสบการณ์ทำงาน",
    job("Digital Marketing Executive", "บริษัท บิวตี้เนชั่น ออนไลน์ จำกัด", "2566 – ปัจจุบัน", [
        "ดูแลงบโฆษณา Facebook Ads และ Google Ads เดือนละ 800,000 บาท ROAS เฉลี่ย 4.2",
        "ทำ SEO หน้าเว็บสินค้า 120 หน้า ทราฟฟิกจาก organic เพิ่ม 65% ใน 1 ปี",
        "วัดผลแคมเปญด้วย Google Analytics 4 และ Looker Studio",
        "วางแผน Content Marketing และทำคอนเทนต์ TikTok ร่วมกับอินฟลูเอนเซอร์ 30 ราย",
    ]) +
    job("Marketing Coordinator", "บริษัท ไทยฟู้ดส์ เดลิเวอรี่ จำกัด", "2564 – 2566", [
        "ออกแบบสื่อโซเชียลด้วย Canva และดูแลเพจ Facebook ผู้ติดตาม 150,000 คน",
    ]))
+ section("การศึกษา", "<p><b>บริหารธุรกิจบัณฑิต สาขาการตลาด</b> — มหาวิทยาลัยธรรมศาสตร์ ปี 2560–2564</p>")
+ section("ทักษะ", ul(["Facebook Ads, Google Ads, TikTok Ads", "SEO, Google Analytics 4, Looker Studio",
                       "Content Marketing, Copywriting", "Canva, Adobe Photoshop (พื้นฐาน)"])))


save("mkt_02_sales_to_marketing_partial_TH.pdf", header(
    "วรเมธ บุญมา", "เจ้าหน้าที่ขาย · สนใจงานการตลาดออนไลน์",
    "ปทุมธานี · woramet.b@example.com · 080-000-0202",
) + section("ข้อมูลส่วนตัว", ul(["เพศ: ชาย · อายุ 27 ปี · สถานภาพ: สมรส · ศาสนา: อิสลาม"]))
+ section("ประสบการณ์ทำงาน",
    job("Sales Executive", "บริษัท โฮมเดโค ดีลเลอร์ จำกัด", "2563 – ปัจจุบัน", [
        "ปิดยอดขายได้ 110% ของเป้าเฉลี่ยทั้งปี ดูแลลูกค้าร้านค้าส่ง 60 ราย",
        "ทำโพสต์ขายสินค้าบน Facebook และ LINE OA ของบริษัท",
    ]))
+ section("การศึกษา", "<p><b>ศิลปศาสตรบัณฑิต สาขาภาษาอังกฤษ</b> — มหาวิทยาลัยรามคำแหง ปี 2558–2562</p>")
+ section("ทักษะ", ul(["การเจรจาต่อรอง, การนำเสนอ", "Microsoft Excel, PowerPoint", "Facebook, LINE OA",
                       "ขับรถยนต์ได้ มีใบขับขี่"])))


save("acc_01_accountant_fit_TH.pdf", header(
    "สุนิสา พรหมมา", "นักบัญชี · ประสบการณ์ 5 ปี",
    "สมุทรปราการ · sunisa.p@example.com · 080-000-0301",
) + section("ประสบการณ์ทำงาน",
    job("นักบัญชีอาวุโส", "บริษัท ไทยพลาสติก อินดัสทรี จำกัด", "2565 – ปัจจุบัน", [
        "ปิดงบการเงินรายเดือนและรายปีตามมาตรฐาน TFRS for NPAEs ส่งผู้สอบบัญชีตรงเวลาทุกปี",
        "จัดทำและยื่นภาษี ภ.ง.ด.1, ภ.ง.ด.3, ภ.ง.ด.53, ภ.พ.30 และ ภ.ง.ด.50",
        "ใช้ SAP Business One บันทึกบัญชีเจ้าหนี้-ลูกหนี้ และกระทบยอดธนาคาร",
    ]) +
    job("นักบัญชี", "สำนักงานบัญชี ศรีนครินทร์ การบัญชี", "2564 – 2565", [
        "ทำบัญชีให้ลูกค้า SME 25 ราย ด้วยโปรแกรม Express", "ใช้ Excel (Pivot Table, VLOOKUP) ทำรายงาน",
    ]))
+ section("การศึกษา", "<p><b>บัญชีบัณฑิต</b> — มหาวิทยาลัยศรีนครินทรวิโรฒ ปี 2560–2564</p>")
+ section("ทักษะ", ul(["ปิดงบการเงิน, TFRS for NPAEs", "ภาษีอากร (ภ.ง.ด., ภ.พ.30)",
                       "SAP Business One, Express", "Microsoft Excel ขั้นสูง"]))
+ section("ใบอนุญาต", ul(["ผู้ทำบัญชีที่ขึ้นทะเบียนกับกรมพัฒนาธุรกิจการค้า"])))


save("hr_01_recruiter_fit_EN.pdf", header(
    "Chayanee Kaewmanee", "HR Recruiter · 4 years",
    "Bangkok · chayanee.k@example.com · 080-000-0401",
) + section("Experience",
    job("Talent Acquisition Specialist", "NextWave Technology Co., Ltd.", "2023 – Present", [
        "Hired 70+ tech roles per year; time-to-hire down from 45 to 28 days.",
        "Sourced candidates on LinkedIn Recruiter and JobsDB; ran structured interviews.",
        "Managed the ATS (Workday) and built a monthly hiring dashboard in Excel.",
    ]) +
    job("HR Officer", "Siam Hotel Group", "2022 – 2023", [
        "End-to-end recruitment for hotel operations; onboarding for 40 staff per quarter.",
    ]))
+ section("Education", "<p>B.A. Psychology — Mahidol University, 2018–2022</p>")
+ section("Skills", ul(["Recruitment, Sourcing, Interviewing, Employer Branding",
                       "LinkedIn Recruiter, JobsDB, Workday, Excel", "Labor Protection Act basics"])))


# สแกน/ถ่ายรูป: ไม่มีข้อความให้อ่าน — ระบบควรปฏิเสธว่าอ่านไม่ได้ (ไม่เสียโควตา)
save("edge_01_scanned_image_only.pdf", header(
    "Piyawat Somsri", "Data Engineer", "piyawat.s@example.com",
) + section("Skills", ul(["Python", "SQL", "Spark", "Airflow"])), scanned=True)
