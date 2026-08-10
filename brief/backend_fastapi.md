# Backend Specification: FastAPI API

เอกสารนี้ระบุรายละเอียดของระบบหลังบ้านที่พัฒนาด้วย **FastAPI** เพื่อให้ทำหน้าที่รับข้อมูลจากหน้าบ้าน (Frontend) ส่งให้ LangGraph และตอบกลับข้อมูลแบบ RESTful API

---

## 📂 1. โครงสร้างโฟลเดอร์ของ API
```text
backend/
├── app/
│   ├── main.py              # จุดรันแอปพลิเคชันหลัก
│   ├── routers/             # ตัวแยกเส้นทาง API
│   │   ├── jobs.py
│   │   ├── candidates.py
│   │   └── hr.py
│   ├── utils/
│   │   └── pdf_extractor.py # ฟังก์ชันแปลงไฟล์ PDF เป็นข้อความ
│   └── database.py          # การเชื่อมต่อ Supabase / Database
├── requirements.txt         # รายการ dependencies
└── .env                     # ค่ากำหนดตัวแปรสภาพแวดล้อม
```

---

## 📦 2. Dependencies (`requirements.txt`)
```text
fastapi>=0.100.0
uvicorn>=0.22.0
langchain>=0.1.0
langgraph>=0.0.10
langchain-google-genai>=0.0.11
supabase>=1.0.3
pydantic>=2.0
python-multipart>=0.0.6
pdfplumber>=0.10.2
python-dotenv>=1.0.0
```

---

## 📡 3. รายละเอียด API Endpoints

### 3.1 Positions & Job Description
*   **POST `/api/v1/jobs`**
    *   **เป้าหมาย**: ส่งข้อความ JD ดิบไปให้ AI ทำการแยกแยะทักษะที่ต้องการ
    *   **Request Body**:
        ```json
        {
          "raw_text": "Looking for a Python Developer with 3 years of experience..."
        }
        ```
    *   **Response**: ส่งกลับข้อมูลที่ถูกสกัดแล้ว (JobRequirement JSON) และบันทึกลงฐานข้อมูล

### 3.2 Resume Upload & Batch Analysis
*   **POST `/api/v1/jobs/{job_id}/resumes`**
    *   **เป้าหมาย**: อัปโหลดไฟล์ Resume (PDF) พร้อมกันหลายไฟล์เพื่อทำการวิเคราะห์
    *   **Content-Type**: `multipart/form-data`
    *   **Request Files**: อาร์เรย์ของไฟล์ PDF
    *   **การทำงานเบื้องหลัง**:
        1. ใช้ `pdfplumber` แกะข้อความจากไฟล์ PDF
        2. บันทึกข้อมูลเบื้องต้นของผู้สมัครลง Database
        3. สั่งทำงานรัน LangGraph Flow ในรูปแบบ Asynchronous (Background Task) เพื่อส่งผลลัพธ์ลง DB ทีละไฟล์

### 3.3 Candidate List & Detail
*   **GET `/api/v1/jobs/{job_id}/candidates`**
    *   **เป้าหมาย**: ดึงข้อมูลรายชื่อผู้สมัครทุกคนที่ลงทะเบียนสมัครตำแหน่งนี้ เรียงตามคะแนน Fit Score
*   **GET `/api/v1/candidates/{candidate_id}`**
    *   **เป้าหมาย**: ดูรายงานวิเคราะห์ตัวบุคคล รายละเอียด Gap Analysis และคำถามสัมภาษณ์งานที่ AI เจนให้

### 3.4 Human-in-the-Loop Override
*   **POST `/api/v1/candidates/{candidate_id}/decision`**
    *   **เป้าหมาย**: HR ส่งผลการอนุมัติหรือปฏิเสธสำหรับแคนดิเดตที่ระบบหยุดรอไว้
    *   **Request Body**:
        ```json
        {
          "decision": "approved",  # "approved" หรือ "rejected"
          "notes": "ทักษะสื่อสารดี เคยทำโปรเจคใกล้เคียงกันมาก"
        }
        ```
    *   **การทำงานเบื้องหลัง**:
        1. อัปเดตตารางตัดสินใจของ HR ในฐานข้อมูล
        2. โหลด State ปัจจุบันของ LangGraph ด้วย `thread_id`
        3. ทำการป้อนค่า `hr_decision` และ `hr_notes` ลงไปใน State
        4. สั่งรัน Graph ต่อจากจุดที่ค้างอยู่ (Resume Execution) เพื่อเข้าสู่ขั้นตอนสัมภาษณ์ / ส่งร่างอีเมล

---

## 🔐 4. การจัดการ CORS ใน `app/main.py`
เนื่องจาก Frontend (Next.js) และ Backend รันคนละพอร์ต ต้องเปิดใช้งาน CORS เสมอ:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="TalentMatch AI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"], # พอร์ตหน้าบ้าน Next.js
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
