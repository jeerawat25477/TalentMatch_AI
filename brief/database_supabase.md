# Database Specification: Supabase (PostgreSQL)

เอกสารนี้ระบุการออกแบบโครงสร้างฐานข้อมูล (Database Schema) บน **Supabase (PostgreSQL)** เพื่อรองรับการเก็บข้อมูลงาน ข้อมูลผู้สมัคร และประวัติสถานะ (State Checkpointer) ของ LangGraph

---

## 📐 1. แผนผังความสัมพันธ์ข้อมูล (Entity-Relationship Diagram)

```text
  [jobs] 1 -------- * [candidates]
    |                      |
    |                      | 1
    |                      |
    * ------------------- * [evaluations] 1 ---- 0..1 [hr_decisions]
```

---

## 💾 2. คำสั่ง SQL สำหรับสร้างตาราง (DDL Schemas)

รันสคริปต์ SQL เหล่านี้ในช่อง **SQL Editor** ของ Supabase เพื่อตั้งค่าตารางเริ่มต้น:

### 2.1 ตารางตำแหน่งงาน (jobs)
```sql
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    raw_text TEXT NOT NULL,
    parsed_criteria JSONB, -- เก็บผลวิเคราะห์จาก JD Analyzer
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);
```

### 2.2 ตารางข้อมูลผู้สมัคร (candidates)
```sql
CREATE TABLE candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    raw_resume_text TEXT, -- ข้อความที่สกัดจาก PDF
    parsed_resume JSONB, -- ข้อมูลประวัติที่จัดระเบียบแล้ว
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);
```

### 2.3 ตารางประเมินผลผู้สมัคร (evaluations)
```sql
CREATE TABLE evaluations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    candidate_id UUID REFERENCES candidates(id) ON DELETE CASCADE,
    fit_score INT NOT NULL CHECK (fit_score >= 0 AND fit_score <= 100),
    gap_analysis JSONB, -- เก็บรายการทักษะที่ผ่านและขาดแคลน
    audit_status VARCHAR(50) DEFAULT 'passed', -- 'passed', 'flagged' (ตรวจจับอคติ)
    audit_log TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);
```

### 2.4 ตารางการตัดสินใจของ HR (hr_decisions)
```sql
CREATE TABLE hr_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id UUID REFERENCES candidates(id) ON DELETE CASCADE UNIQUE,
    decision VARCHAR(50) NOT NULL CHECK (decision IN ('approved', 'rejected', 'pending')),
    notes TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);
```

---

## 🔄 3. การเก็บความจำของ LangGraph (State Checkpointer)
เพื่อทำระบบหยุดและไปต่อ (Human-in-the-Loop) ได้อย่างเสถียร เราต้องเปิดใช้งาน Checkpointer ให้เซฟลงฐานข้อมูลหลัก (แทนการใช้หน่วยความจำชั่วคราว `:memory:`) 

สคริปต์ Python ในฝั่งหลังบ้านจะใช้ `PostgresSaver` จากแพ็คเกจ `langgraph-checkpoint-postgres` เพื่อเชื่อมต่อกับ Supabase:

```python
from psycopg import Connection
from langgraph.checkpoint.postgres import PostgresSaver

# เชื่อมต่อกับ Supabase PostgreSQL Connection String
connection_string = "postgresql://postgres:[PASSWORD]@db.[PROJECT_ID].supabase.co:5432/postgres"

# เปิดการเชื่อมต่อและลงทะเบียน saver
with Connection.connect(connection_string) as conn:
    saver = PostgresSaver(conn)
    # ทำการติดตั้งตารางสำหรับการบันทึก checkpoint อัตโนมัติ (ครั้งแรก)
    saver.setup()
```
เมื่อรันคำสั่ง `saver.setup()` ตัวระบบจะไปสร้างตารางในฐานข้อมูล Supabase เพื่อคอยบันทึกสถานะของ Graph เผื่อเวลาที่มีสายหลุดหรือแอปหลังบ้านถูกรีสตาร์ทข้อมูลประวัติก็จะไม่สูญหายครับ
