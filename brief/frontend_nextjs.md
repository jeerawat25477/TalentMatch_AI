# Frontend Specification: Next.js Web App

เอกสารนี้ระบุรายละเอียดของหน้าจอแสดงผล (User Interface) และการเชื่อมต่อฝั่งหน้าบ้านด้วย **Next.js (App Router)** เพื่อให้ระบบดูหรูหรา น่าใช้งาน และตอบสนองรวดเร็ว

---

## 📂 1. โครงสร้างโฟลเดอร์ฝั่งหน้าบ้าน
```text
frontend/
├── app/
│   ├── layout.tsx           # โครงสร้างพื้นฐานหลัก (Navbar/Sidebar)
│   ├── page.tsx             # หน้าเลือกตำแหน่งงานหลัก
│   ├── jobs/
│   │   ├── new/
│   │   │   └── page.tsx     # หน้ากรอกข้อมูล JD ใหม่
│   │   └── [id]/
│   │       ├── page.tsx     # หน้า Dashboard ของตำแหน่งงานนั้นๆ
│   │       └── candidates/
│   │           └── [candidate_id]/
│   │               └── page.tsx # หน้าวิเคราะห์ผู้สมัครแบบละเอียด (Deep Dive)
├── components/              # คอมโพเนนต์ที่ใช้ซ้ำ
│   ├── radar-chart.tsx      # กราฟเปรียบเทียบทักษะ
│   ├── file-upload.tsx      # ช่องลากวางไฟล์ PDF
│   └── candidate-table.tsx  # ตารางแสดงรายชื่อผู้สมัคร
```

---

## 🎨 2. แนวทางด้านดีไซน์และโทนสี (Premium Aesthetics)
*   **Theme**: Dark Mode (สีหลัก: ดำขรึม `Slate-900` ผสมเทาอุ่น `Slate-800` ตัดด้วยสีเด่นสะท้อนแสง)
*   **Primary Color (สีหลัก)**: `Violet-500` (#8B5CF6) เพื่อให้ความรู้สึกไฮเทคและพรีเมียม
*   **Success (สีผ่านเกณฑ์)**: `Emerald-500` (#10B981)
*   **Warning (สีรอการตัดสินใจ)**: `Amber-500` (#F59E0B)
*   **Typography**: ฟอนต์ **Inter** หรือ **Outfit** (จาก Google Fonts) เพื่อความโมเดิร์น
*   **Layout Style**: **Glassmorphism** (ใช้แผงควบคุมโปร่งแสง มีความเบลอของพื้นหลัง `backdrop-blur-md` และขอบสีขาวจางๆ)

---

## 🖥️ 3. การออกแบบส่วนติดต่อผู้ใช้งาน (UI Screens)

### 3.1 หน้าจอ Job Setup (สร้างประกาศงานใหม่)
*   ประกอบด้วยช่อง Input ขนาดใหญ่สำหรับป้อนข้อความ JD
*   มีระบบพรีวิวอัตโนมัติแสดงว่า AI ดึง Required Skills และประวัติออกมาเป็นตัวแปรแบบเรียลไทม์ได้ถูกต้องหรือไม่ ก่อนกดบันทึก

### 3.2 หน้าจอ Job Dashboard (สรุปสถานะการสมัคร)
*   **Header Section**: แสดงข้อมูลติตถ์ของประกาศงาน, จำนวนใบสมัครทั้งหมด, อัตราผ่านเกณฑ์เฉลี่ย
*   **File Drop Zone**: ให้ HR ลากไฟล์ PDF Resume หลายๆ ไฟล์มาวางพร้อมกัน มี ProgressBar แสดงเปอร์เซ็นต์ความก้าวหน้าในการอัปโหลด
*   **Candidate Table**: ตารางที่จัดอันดับผู้สมัครตาม Fit Score
    *   คอลัมน์: ลำดับที่, ชื่อผู้สมัคร, คะแนน (Fit Score Progress Bar), สถานะการเช็คอคติ (Audit Status Tag), สถานะการสัมภาษณ์
    *   หากผู้สมัครคนใดต้องรอการตัดสินใจของ HR จะมี Badge สีส้มแจ้งเตือนกะพริบเบาๆ เขียนว่า **"Needs Review"**

### 3.3 หน้าจอ Candidate Deep Dive (วิเคราะห์รายบุคคล)
*   **Left Column (สรุปประวัติ)**: ข้อมูลส่วนตัว, ประสบการณ์ และประวัติย่อ
*   **Middle Column (วิเคราะห์ส่วนต่าง)**:
    *   **Skill Gap Visualization**: ใช้ กราฟเรดาร์ (Radar Chart) แสดงความทับซ้อนของทักษะที่ต้องการ vs ทักษะที่มี
    *   รายการทักษะที่ผ่านเกณฑ์ (เขียว) และทักษะที่ต้องฝึกเพิ่ม/ไม่มีในใบสมัคร (แดง)
*   **Right Column (แผนสัมภาษณ์ & การติดต่อ)**:
    *   **Interview Guide**: แสดงคำถามที่ AI ออกแบบมาเฉพาะตัวบุคคล พร้อมเฉลยแนวคำตอบที่ HR คาดหวังจะได้
    *   **Communication Drawer**: กล่องข้อความแสดงอีเมลร่างนัดหมายสัมภาษณ์/ปฏิเสธ สามารถแก้ไขสดบนหน้าจอได้ทันทีก่อนกดส่ง
    *   **Decision Area**: ปุ่มใหญ่สำหรับ HR กด **[Approve to Interview]** หรือ **[Reject Candidate]**

---

## ⚡ 4. การเชื่อมโยง API ด้วย Next.js `fetch`
ตัวอย่างการดึงข้อมูลและจัดการสถานะส่งต่อข้อมูล (Decision) ไปยัง FastAPI หลังบ้าน:

```typescript
async function handleHRDecision(candidateId: string, decision: 'approved' | 'rejected', notes: string) {
  const response = await fetch(`http://localhost:8000/api/v1/candidates/${candidateId}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, notes }),
  });
  
  if (response.ok) {
    // โหลดข้อมูลหน้าแดชบอร์ดใหม่เพื่อแสดงผลอัปเดตล่าสุด
    mutateCandidateData();
  }
}
```
