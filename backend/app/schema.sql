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

-- กันอัปโหลดไฟล์เดิมซ้ำ: hash ของไบต์ PDF ต่อหนึ่งตำแหน่งงาน
-- (ชื่อไฟล์เปลี่ยนได้ ส่วนอีเมลยังไม่มีตอนอัปโหลด จึงใช้ hash เป็นตัวชี้ขาด)
-- แถวเก่าเป็น NULL ได้ — Postgres ถือว่า NULL แต่ละตัวไม่เท่ากัน จึงอยู่ร่วมกันได้โดยไม่ต้อง backfill
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS resume_sha256 CHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS candidates_job_resume_uniq
    ON candidates (job_id, resume_sha256);

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
-- ร่องรอยลูป critique/revise (bias_auditor -> matcher): เกณฑ์ที่ถอด + คะแนนก่อน/หลัง
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS bias_revision JSONB;
-- หลักฐานจากเรซูเม่ของแต่ละทักษะที่ตรงเกณฑ์ {ชื่อทักษะแบบ JD: ข้อความที่ยกมา}
-- ผ่านการตรวจกับข้อความเรซูเม่จริงแล้ว (agents/evidence.py) — แถวเก่าเป็น NULL ตลอดไป
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS skill_evidence JSONB;
-- ประโยคอธิบายที่มาของ fit_score (สร้างจาก template ใน agents/explain.py ไม่ได้เรียก LLM)
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS score_explanation TEXT;
-- ความมั่นใจของผลวิเคราะห์ 'high'|'medium'|'low' (คนละมิติกับ fit_score — บอกว่าผลนี้
-- อิงข้อมูลครบแค่ไหน) คำนวณ deterministic ใน agents/bands.py ไม่ได้ให้ LLM ประเมินตัวเอง
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS confidence VARCHAR(10);

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

-- ============================================================
-- เทมเพลตอีเมลที่ HR บันทึกไว้ใช้ซ้ำ
-- ============================================================
-- ชั้นอำนวยความสะดวกล้วน ๆ: เก็บร่าง subject/body ที่ HR แก้บ่อย ๆ ไว้เรียกใช้ซ้ำ
-- ไม่เกี่ยวกับเส้นทางการส่งอีเมลจริง (ยังผ่าน /email/send + email_sender.py เหมือนเดิม)
-- HR ยังต้องเห็นและยืนยันเนื้อหาบนจอก่อนส่งเสมอ — เทมเพลตแค่เติมช่องให้ ไม่ส่งเอง
--
-- ไม่มี user_id: ระบบตอนนี้มี admin คนเดียว (ดู CLAUDE.md เรื่อง auth)
-- ถ้ารองรับหลายผู้ใช้เมื่อไหร่ค่อยเพิ่มคอลัมน์ อย่าเผื่อล่วงหน้า
CREATE TABLE IF NOT EXISTS email_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,                     -- ชื่อที่ HR ตั้งเอง
    -- ต้องตรงกับ EmailDraft.kind (app/agents/models.py) เพื่อให้กรองเทมเพลต
    -- ให้ตรงสถานการณ์ที่กำลังร่างอยู่ ไม่เอาอีเมลปฏิเสธไปโผล่ตอนเชิญสัมภาษณ์
    kind VARCHAR(20) NOT NULL CHECK (kind IN ('invitation', 'rejection')),
    subject_template TEXT NOT NULL,
    body_template TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- ============================================================
-- คิวงานประมวลผล (แทน BackgroundTasks ที่หายไปพร้อมโปรเซส)
-- ============================================================
-- BackgroundTasks อยู่ในหน่วยความจำของโปรเซส: container รีสตาร์ต / hot-reload /
-- โควตา LLM หมด แล้วงานที่ค้างหายทันที ไม่มีอะไรรันต่อ ผู้สมัครจึงค้างเป็น
-- "กำลังวิเคราะห์…" ตลอดกาลจนกว่า HR จะเห็นป้าย stalled แล้วกดเอง
-- ตารางนี้ทำให้ "งานที่ต้องทำ" อยู่ใน DB — worker (app/queue_worker.py) หยิบไปทำ
-- ทีละชิ้น และแถวที่ค้าง 'running' ตอนแอปบูตใหม่ถูกดึงกลับเป็น 'queued' อัตโนมัติ
CREATE TABLE IF NOT EXISTS processing_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- ON DELETE CASCADE ได้และควรมี (ต่างจากตาราง checkpoint ที่ไม่มี FK เลย) —
    -- ลบผู้สมัครแล้วงานที่ค้างในคิวของเขาต้องหายตาม ไม่งั้น worker จะหยิบงาน
    -- ของคนที่ไม่มีอยู่แล้วขึ้นมารันจนล้มทุกครั้ง
    candidate_id UUID NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    job_id UUID,
    -- บอก worker ว่าต้องเรียกฟังก์ชันไหนใน agents/runner.py
    kind TEXT NOT NULL CHECK (kind IN ('process', 'resume_after_decision', 'reprocess')),
    -- เก็บเฉพาะ arg ที่เล็กและไม่มีที่อยู่อื่น (decision/notes)
    -- ส่วน raw_jd / analyzed_jd / resume_text ให้ worker อ่านสดจาก DB ตอนรัน:
    -- ข้อความเรซูเม่ยาวหลักพันตัวอักษร และคิวอยู่ข้ามวันได้ สำเนาที่แช่ไว้จะเก่า
    payload JSONB,
    -- 'deferred_quota' = พักไว้เพราะโควตา AI วันนี้ไม่พอ **ไม่ใช่สถานะปลายทาง**
    -- worker หยิบกลับมาเช็คใหม่เองเป็นระยะ จึงไม่ต้องมี cron รีเซ็ตตอนเที่ยงคืน
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'done', 'failed', 'deferred_quota')),
    attempts INT NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- worker ดึงงานเก่าสุดที่ยังรอ — ดัชนีตรงกับ WHERE status ... ORDER BY created_at
CREATE INDEX IF NOT EXISTS processing_queue_pick
    ON processing_queue (status, created_at);

-- ตัวนับ chat call รายวัน (โควตา Gemini free tier = 20 call/วัน **ต่อโมเดล**)
-- backoff ใน agents/llm.py แก้ได้แค่ลิมิตต่อนาที (RPM) — ลิมิตต่อวัน (RPD) retry ไปก็ไม่หาย
-- ต้องรู้ว่าวันนี้ใช้ไปเท่าไรก่อนจะยิงงานถัดไป ไม่งั้น batch ใหญ่จะตายเงียบยกแผง
--
-- usage_date ตัดวันตาม **รอบจริงของ Google** คือเที่ยงคืน Pacific (ดู app/llm_quota.py)
-- ไม่ใช่ UTC: เคยใช้ UTC แล้ววัดได้ว่าตอบวันที่ผิด 30.6% ของเวลาทั้งปี และช่องว่างนั้น
-- คร่อมเวลาทำงานช่วงเช้าของ HR พอดี ทำให้ยอดของเช้าถูกคิดเข้า "วันนี้" ทั้งที่ Google
-- คิดเข้า "เมื่อวาน" ช่วงบ่ายจึงถูกพักงานทิ้งไว้ทั้งที่โควตาจริงรีเซ็ตไปแล้ว
-- (ปรับเขตเวลาได้ด้วย GEMINI_QUOTA_TZ · ยังมีการดัก 429 จริงเป็น deferred_quota อีกชั้น)
CREATE TABLE IF NOT EXISTS llm_quota_usage (
    usage_date DATE NOT NULL,
    model TEXT NOT NULL,
    chat_calls_used INT NOT NULL DEFAULT 0,
    PRIMARY KEY (usage_date, model)
);
