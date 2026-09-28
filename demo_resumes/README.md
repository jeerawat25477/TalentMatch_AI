# เรซูเม่ทดสอบ / สาธิต

บุคคล บริษัท เบอร์โทร และอีเมล **สมมติทั้งหมด** (อีเมลใช้ `@example.com`) · มหาวิทยาลัยเป็นชื่อจริง
ไฟล์ PDF อยู่ใน `pdf/` · สร้างใหม่ได้ด้วย `python demo_resumes/generate.py` (ใช้ Edge บน Windows)

**ค่าใช้จ่าย:** อัปโหลดเรซูเม่ = ประมาณ 5 call ต่อคน · สร้างตำแหน่งใหม่ = 1 call · ไฟล์สแกนไม่เสีย

## AI Engineer (ใช้กับตำแหน่ง AI Engineer ที่มีอยู่)

| ไฟล์ | คนแบบไหน | ผลที่ควรเห็น |
|---|---|---|
| `ai_01_strong_fit_EN.pdf` | AI Engineer 4 ปี มีครบเกือบทุกข้อ | คะแนนสูง → ผ่าน |
| `ai_02_data_scientist_partial_TH.pdf` | Data Scientist ไม่มีงาน LLM | ตรงบางส่วน → ไม่ผ่านหรือรอ HR |
| `ai_03_new_grad_personal_info_TH.pdf` | จบใหม่ มีโปรเจกต์ RAG · **ใส่ เพศ อายุ ศาสนา สถานะทหาร** แบบเรซูเม่ไทย | ตรงบางส่วน · ข้อมูลส่วนตัวต้องไม่มีผลต่อคะแนน |
| `ai_04_backend_career_switch_EN.pdf` | Backend Java จะย้ายสาย · ได้ Docker/K8s/Git/CI/CD | ตรงฝั่ง DevOps แต่ขาด ML → ไม่ผ่าน |
| `ai_05_two_column_canva_style_EN.pdf` | เรซูเม่ 2 คอลัมน์แบบ Canva (ML สาย Computer Vision) | ทดสอบว่าอ่านเลย์เอาต์ 2 คอลัมน์ได้ |

## ฝ่ายอื่น — สร้างตำแหน่งจากประกาศข้างล่างก่อน แล้วค่อยอัปโหลด

**Digital Marketing Executive** → `mkt_01` (ตรง) · `mkt_02` (สายขาย ตรงน้อย · มีเพศ/ศาสนา/สถานภาพ)
```
ตำแหน่ง: Digital Marketing Executive

หน้าที่
- วางแผนและยิงโฆษณาออนไลน์ ดูแลงบประมาณรายเดือน
- วัดผลแคมเปญและทำรายงานให้ผู้บริหาร

คุณสมบัติ
- ประสบการณ์ 2 ปีขึ้นไปด้าน Digital Marketing
- ยิงโฆษณา Facebook Ads และ Google Ads ได้
- ใช้ Google Analytics วัดผลได้
- เข้าใจ SEO และ Content Marketing
- ใช้ Canva หรือ Adobe Photoshop ได้
- มีประสบการณ์ TikTok Ads จะพิจารณาเป็นพิเศษ
```

**นักบัญชี** → `acc_01` (ตรง)
```
ตำแหน่ง: นักบัญชี

คุณสมบัติ
- วุฒิปริญญาตรี สาขาบัญชี
- ปิดงบการเงินรายเดือนได้ เข้าใจมาตรฐาน TFRS for NPAEs
- ยื่นภาษี ภ.ง.ด.1, ภ.ง.ด.3, ภ.ง.ด.53 และ ภ.พ.30 ได้
- ใช้โปรแกรม Express หรือ SAP Business One ได้
- ใช้ Excel ได้ดี
- เป็นผู้ทำบัญชีที่ขึ้นทะเบียนแล้วจะพิจารณาเป็นพิเศษ
```

**HR Recruiter** → `hr_01` (ตรง)
```
Position: HR Recruiter

Qualifications
- 2+ years of recruitment experience
- Sourcing on LinkedIn and JobsDB
- Structured interviewing
- Experience with an ATS such as Workday or SAP SuccessFactors
- Employer branding is a plus
```

## ไฟล์ทดสอบกรณีพิเศษ

| ไฟล์ | ผลที่ควรเห็น |
|---|---|
| `edge_01_scanned_image_only.pdf` | เรซูเม่ที่สแกน/ถ่ายรูป ไม่มีข้อความ → ระบบ**ปฏิเสธ**ว่าอ่านไม่ได้ ไม่เสียโควตา |
| อัปโหลดไฟล์เดิมซ้ำในตำแหน่งเดียวกัน | ระบบข้ามไฟล์ซ้ำ ไม่วิเคราะห์ใหม่ |
| อัปโหลด `acc_01` เข้าตำแหน่ง AI Engineer | คะแนนต่ำ — สมัครผิดสาย |
