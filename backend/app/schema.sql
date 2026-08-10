-- TalentMatch AI — App tables (idempotent)
-- อ้างอิง database_supabase.md; ใช้ CREATE TABLE IF NOT EXISTS เพื่อรันซ้ำได้
-- ตาราง checkpoint* ของ LangGraph สร้างแยกผ่าน PostgresSaver.setup()

CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    raw_text TEXT NOT NULL,
    parsed_criteria JSONB,                         -- ผลวิเคราะห์จาก JD Analyzer
    -- วงจรชีวิตของตำแหน่ง: 'open' รับสมัครอยู่ | 'closed' ปิดรับ (รับพนักงานได้แล้ว)
    -- ปิดงานแทนการลบ เพื่อรักษาผู้สมัคร/คะแนน/หลักฐานการส่งอีเมล และคลังเวกเตอร์ไว้
    status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    closed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- เผื่อ DB ที่สร้างตาราง jobs ไว้ก่อนเพิ่มสองคอลัมน์นี้ (idempotent)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'open';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP WITH TIME ZONE;
-- CHECK แยกออกมาเพราะ ADD COLUMN IF NOT EXISTS ไม่พา constraint ไปด้วยตอนคอลัมน์มีอยู่แล้ว
DO $$
BEGIN
    ALTER TABLE jobs ADD CONSTRAINT jobs_status_check
        CHECK (status IN ('open', 'closed'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    raw_resume_text TEXT,                           -- ข้อความที่สกัดจาก PDF
    parsed_resume JSONB,                            -- ประวัติที่จัดระเบียบแล้ว
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    candidate_id UUID REFERENCES candidates(id) ON DELETE CASCADE,
    fit_score INT NOT NULL CHECK (fit_score >= 0 AND fit_score <= 100),
    gap_analysis JSONB,                             -- ทักษะที่ผ่าน/ขาดแคลน
    audit_status VARCHAR(50) DEFAULT 'passed',      -- 'passed' | 'flagged'
    audit_log TEXT,
    interview_plan JSONB,                           -- คำถามสัมภาษณ์จาก planner
    email_draft JSONB,                              -- ร่างอีเมลจาก drafter (เชิญ/ปฏิเสธ)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- เผื่อ DB ที่สร้างตารางไว้ก่อนเพิ่มสองคอลัมน์นี้ (idempotent)
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS interview_plan JSONB;
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS email_draft JSONB;
-- บันทึกการส่งอีเมลจริง (เวลา + ผู้รับ) เพื่อกันส่งซ้ำและเป็นหลักฐาน audit
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS email_sent_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS email_sent_to TEXT;
-- นับจำนวนครั้งที่ส่งอีเมล (รวมส่งซ้ำ) เพื่อโชว์ "ส่งแล้ว N ครั้ง" บนหน้าเว็บ
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS email_send_count INT NOT NULL DEFAULT 0;
-- ผู้สมัครเก่าที่โปรไฟล์คล้ายกัน จาก retrieval agent (RAG, เปิด/ปิดด้วย RAG_ENABLED)
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS similar_candidates JSONB;

CREATE TABLE IF NOT EXISTS hr_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id UUID REFERENCES candidates(id) ON DELETE CASCADE UNIQUE,
    decision VARCHAR(50) NOT NULL CHECK (decision IN ('approved', 'rejected', 'pending')),
    notes TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- คลังเวกเตอร์สำหรับค้นหาผู้สมัครเก่าด้วยความหมาย (vectordb_chroma.md §1.2)
-- ต้องใช้อิมเมจ pgvector/pgvector:pg16 (ดู docker-compose.yml)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS resume_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- UNIQUE เพื่อ upsert ได้เมื่อ resume ถูกประมวลผลซ้ำ (แนวเดียวกับ hr_decisions)
    candidate_id UUID REFERENCES candidates(id) ON DELETE CASCADE UNIQUE,
    embedding VECTOR(768),                          -- gemini-embedding-001 ตัดเหลือ 768 มิติ
    content TEXT,                                   -- ข้อความที่นำไป embed
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS resume_embeddings_hnsw
    ON resume_embeddings USING hnsw (embedding vector_cosine_ops);

-- ผู้ใช้ระบบ (HR) สำหรับล็อกอิน — รหัสผ่านเก็บเป็น bcrypt hash เท่านั้น
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- ทะเบียนพนักงาน — ผู้สมัครที่ผ่านสัมภาษณ์แล้วถูกรับเข้าทำงาน
-- เป็นข้อมูลถาวร: FK ไป candidates/jobs แบบ *ไม่* ON DELETE CASCADE โดยตั้งใจ
--   (routers มี blocker คืน 409 กันลบ candidate/job ที่มีพนักงานผูกอยู่)
-- full_name/email เก็บเป็น snapshot ให้ระเบียนอ่านได้เองแม้ผู้สมัครถูกแก้ภายหลัง
CREATE TABLE IF NOT EXISTS employees (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- หนึ่งผู้สมัครรับเข้าได้ครั้งเดียว (แนวเดียวกับ hr_decisions)
    candidate_id UUID NOT NULL UNIQUE REFERENCES candidates(id),
    job_id UUID REFERENCES jobs(id),                -- ตำแหน่งที่รับเข้า
    full_name VARCHAR(255) NOT NULL,                -- snapshot
    email VARCHAR(255),                             -- snapshot
    position VARCHAR(255) NOT NULL,                 -- ค่าเริ่มต้น = job.title
    department VARCHAR(255),
    status VARCHAR(20) NOT NULL DEFAULT 'probation'
        CHECK (status IN ('probation', 'permanent', 'terminated', 'suspended')),
    salary NUMERIC(12, 2),
    start_date DATE,                                -- วันเริ่มงาน
    probation_end_date DATE,                        -- วันครบทดลองงาน
    hr_notes TEXT,
    hired_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);
