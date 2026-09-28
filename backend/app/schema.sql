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
-- เกณฑ์ทักษะที่ AI ดึงไว้ตอนสร้างตำแหน่ง เก็บตอน HR แก้ parsed_criteria ครั้งแรก — ให้กด
-- "คืนค่าตามที่ AI ดึง" ได้ และเป็นข้อมูลว่า AI ดึงผิดบ่อยแค่ไหน (NULL = ยังไม่เคยแก้)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS ai_criteria JSONB;
-- เวลาที่ HR แก้เกณฑ์ล่าสุด · NULL = parsed_criteria ยังเป็นของ AI ล้วน
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS criteria_edited_at TIMESTAMP WITH TIME ZONE;
-- ป้ายดิบที่ jd_analyzer ติดให้ทักษะแต่ละคำ (JDExtraction: kind/necessity/section/group)
-- parsed_criteria คือผลที่โค้ดจัดฝั่งจากป้ายเหล่านี้ · เก็บไว้ให้ทางแก้ข้อ 3 (กลุ่ม "ข้อใดข้อหนึ่ง")
-- ใช้ป้าย one_of ได้โดยไม่ต้องให้ AI อ่านประกาศใหม่ · NULL = ตำแหน่งที่สร้างก่อนมีคอลัมน์นี้
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS jd_extraction JSONB;
-- ผลตรวจอคติของประกาศ ทำครั้งเดียวตอนสร้างตำแหน่ง (กฎตายตัว + LLM หนึ่ง call) แล้วผู้สมัคร
-- ทุกคนอ่านผลเดียวกัน — เดิม bias_auditor เรียก LLM ตรวจประกาศเดิมซ้ำทุกคน
-- รูป: {status, log, jd_criteria, biased_required_skills, biased_preferred_skills, llm_checked}
-- NULL = ตำแหน่งที่สร้างก่อนมีคอลัมน์นี้ โหนดจะใช้กฎตายตัวอย่างเดียว (scripts/backfill_jd_audit.py)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS jd_audit JSONB;
-- ถ้อยคำในผลตรวจที่ HR ยืนยันว่า "จำเป็นกับงานนี้จริง" (เช่น เพศหญิงสำหรับงานตรวจค้นตัว)
-- [{phrase, reason, by, at}] — แยกจาก jd_audit โดยตั้งใจ: อันนั้นคือผลของเครื่อง อันนี้คือการตัดสินใจ
-- ของคน ใครยืนยัน เมื่อไร เพราะอะไร ต้องย้อนตรวจได้ · ไม่มีผลกับคะแนนใด ๆ (เพศ/สัญชาติไม่เคยอยู่ในคะแนน)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS bias_acknowledgements JSONB NOT NULL DEFAULT '[]'::jsonb;
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
-- คะแนนก่อนถูกคำนวณใหม่เพราะ HR แก้เกณฑ์ทักษะ + เวลาที่คำนวณ — ใช้ขึ้นป้าย
-- "เกณฑ์เปลี่ยน ตรวจอีกครั้ง" เมื่อแบนด์เปลี่ยน (ระบบไม่เดินกราฟใหม่เอง ให้ HR ตัดสิน)
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS rescored_from INT;
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS rescored_at TIMESTAMP WITH TIME ZONE;
-- ร่างอีเมลฉบับที่ HR แก้เองและกดบันทึก — **คนละคอลัมน์กับ email_draft โดยตั้งใจ**
-- email_draft เป็นของ email_drafter: กราฟเดินรอบใหม่แล้วเขียนทับ และ runner ตั้งเป็น
-- NULL ได้เมื่อ drafter ล้ม ถ้าเก็บร่างของ HR ไว้ที่นั่น งานที่พิมพ์เองจะหายโดยไม่มีใครรู้
-- NULL = ยังไม่เคยแก้/กดกลับไปใช้ร่างของ AI · {subject, body} เหมือน email_draft
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS email_draft_edited JSONB;
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS email_draft_edited_at TIMESTAMP WITH TIME ZONE;

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

-- ============================================================
-- ค่าตั้งค่าระดับระบบ (key-value ทั่วไป)
-- ============================================================
-- value เป็น jsonb ทั่วไป ไม่ผูกกับฟีเจอร์ใดฟีเจอร์หนึ่ง — setting ตัวถัดไปใช้ key ใหม่ได้เลย
-- ไม่ต้องเพิ่มคอลัมน์ · อ่านผ่าน app/settings.py ซึ่งแคชสั้น ๆ ให้ (worker อ่านทุกรอบ)
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- ปากทางรับใบสมัครทางอีเมล — **ดีฟอลต์ปิดเสมอ** (ปลอดภัยโดยปริยาย)
-- DO NOTHING สำคัญ: ถ้าใช้ DO UPDATE ทุกครั้งที่บูตจะไปทับสวิตช์ที่ HR เปิดไว้ให้กลับเป็นปิด
--
-- uid_validity ไม่ใช่ของแถม: UID ของ IMAP มีความหมายเฉพาะคู่กับ UIDVALIDITY ของกล่องนั้น
-- ถ้ากล่องถูกสร้างใหม่/ย้ายผู้ให้บริการ ค่านี้เปลี่ยน แล้ว last_uid_seen เดิมจะกลายเป็น
-- เลขคนละชุด — ไม่เช็คแล้วจะข้ามเมลใหม่ทั้งกล่องเงียบ ๆ หรือดูดซ้ำทั้งกล่อง
INSERT INTO app_settings (key, value)
VALUES ('email_intake',
        '{"enabled": false, "last_uid_seen": null, "uid_validity": null,
          "last_poll_at": null, "last_error": null}')
ON CONFLICT (key) DO NOTHING;

-- แสดงรูปผู้สมัครบนหน้าคัดกรอง — **ดีฟอลต์ปิดเสมอ** (เห็นหน้าก่อนตัดสินอาจทำให้ไม่เป็นกลาง)
-- สวิตช์นี้คุมแค่ "แสดงไหม" ไม่ได้คุม "ดึงไหม" — รูปถูกดึงตอนรับไฟล์ทุกครั้ง (ดู candidate_photos)
-- DO NOTHING ด้วยเหตุผลเดียวกับ email_intake: บูตใหม่ต้องไม่ทับค่าที่ HR ตั้งไว้
INSERT INTO app_settings (key, value)
VALUES ('screening_photos', '{"enabled": false}')
ON CONFLICT (key) DO NOTHING;

-- บันทึกทุกฉบับที่ปากทางอีเมลเห็น — ทั้งที่รับเข้าและที่ปฏิเสธ
-- มีไว้เพื่อสองอย่าง: (1) ให้ HR เห็นว่าเมลที่จับคู่ไม่ได้มีกี่ฉบับและเพราะอะไร
-- โดยไม่ต้องเปิด container log (2) ให้ตัวนับรายวันคำนวณจากข้อมูลจริงด้วย GROUP BY
-- แทนตัวแปรในหน่วยความจำที่รีเซ็ตทุกครั้งที่ backend รีโหลด (ใน dev เกิดบ่อยมาก)
--
-- job_id / candidate_id **ไม่มี FK โดยตั้งใจ** — log ต้องอยู่ต่อแม้ตำแหน่งงานหรือผู้สมัคร
-- ถูกลบไปแล้ว ไม่งั้นประวัติการรับเข้าจะหายพร้อมกับสิ่งที่มันบันทึกไว้
CREATE TABLE IF NOT EXISTS email_intake_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    uid TEXT,
    uid_validity TEXT,
    from_addr TEXT,
    subject TEXT,
    job_id UUID,
    candidate_id UUID,
    outcome TEXT NOT NULL CHECK (outcome IN (
        'matched', 'unmatched', 'duplicate', 'unreadable',
        'no_attachment', 'job_closed', 'error')),
    detail TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS email_intake_log_recent
    ON email_intake_log (created_at DESC);

-- ============================================================
-- กระดานติดตามผู้สมัครหลังผ่านการคัดกรอง
-- ============================================================
-- เลเยอร์บาง ๆ ทับผลของกราฟ: กราฟตัดสินว่า "ควรเชิญไหม" จบแล้วก็จบ ส่วนตารางนี้ตาม
-- ต่อว่าคนที่เชิญไปแล้วเดินไปถึงไหน (นัดหรือยัง สัมภาษณ์แล้วหรือยัง ยื่นข้อเสนอหรือยัง)
-- **ไม่เคยเขียนอะไรกลับเข้ากราฟ** และไม่มีการเรียก LLM ในเส้นทางนี้เลย
--
-- ON DELETE CASCADE ที่นี่ ต่างจาก employees.candidate_id ที่เป็น FK ธรรมดาโดยตั้งใจ:
-- stage เป็นข้อมูลชั่วคราวระหว่างกระบวนการ ลบผู้สมัครทิ้งแล้วหายตามได้ ส่วนระเบียน
-- พนักงานเป็นของถาวรที่ต้องกันการลบไว้ (routers คืน 409 ถ้าพยายามลบ)
CREATE TABLE IF NOT EXISTS hiring_stage (
    candidate_id UUID PRIMARY KEY REFERENCES candidates(id) ON DELETE CASCADE,
    -- ⚠️ **ไม่มี 'hired' ในรายการนี้โดยตั้งใจ** — "รับเข้าแล้ว" อนุมานจากการมีแถวใน
    -- employees (candidate_id เป็น UNIQUE อยู่แล้ว) ไม่ใช่ค่าในคอลัมน์นี้ ถ้าเก็บทั้งสองที่
    -- จะมีวันที่สองแหล่งขัดกันเอง แล้วไม่มีใครรู้ว่าอันไหนจริง
    stage TEXT NOT NULL DEFAULT 'invited'
        CHECK (stage IN ('invited', 'scheduled', 'interviewed', 'offer', 'declined')),
    -- เวลาที่ย้ายขั้นล่าสุดจริง ๆ — จึงห้ามสร้างแถวนี้ตอน GET (write-on-read) ไม่งั้น
    -- ค่านี้จะกลายเป็น "เวลาที่ HR เปิดหน้ากระดาน" ซึ่งไม่ได้บอกอะไรเลย
    moved_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    note TEXT
);
-- วันเวลานัดสัมภาษณ์ — NULL = ยังไม่ได้ตั้ง · ไม่ผูกกับ stage: HR ย้ายขั้นโดยไม่ใส่เวลา
-- หรือใส่เวลาโดยไม่ย้ายขั้นก็ได้ · เก็บเป็น TIMESTAMPTZ เพราะ HR กรอกเป็นเวลาท้องถิ่น
-- แต่ลิงก์ Google Calendar ต้องการเวลา UTC ถ้าเก็บแบบไม่มีโซนจะแปลงผิดเงียบ ๆ
ALTER TABLE hiring_stage ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMP WITH TIME ZONE;
-- สถานที่หรือลิงก์ประชุม ข้อความอิสระ ไม่ validate รูปแบบโดยตั้งใจ
-- ⚠️ ไม่มีคอลัมน์อีเมลผู้เข้าร่วม และห้ามเพิ่ม: ลิงก์ปฏิทินต้องไม่ทำให้ Google ส่งคำเชิญ
-- ถึงผู้สมัครเองโดยที่ HR ยังไม่ได้ยืนยันเนื้อหา (ดู "Email send is synchronous and HR-gated")
ALTER TABLE hiring_stage ADD COLUMN IF NOT EXISTS location TEXT;

-- ============================================================
-- ผลสัมภาษณ์จริง — ground truth ชุดเดียวที่ระบบมี
-- ============================================================
-- กราฟร่างคำถามให้ HR (evaluations.interview_plan) แล้วหน้าที่ของมันจบตรงนั้น ตารางนี้
-- เก็บสิ่งที่เกิดขึ้น "หลังจาก" คนไปสัมภาษณ์จริงมาแล้ว ซึ่งเป็นข้อมูลชุดเดียวที่บอกได้ว่า
-- คะแนนของ AI แม่นแค่ไหน (คนคะแนน 85 สัมภาษณ์แล้วไม่ผ่านบ่อยไหม) — วัตถุดิบของเฟส 5
-- calibration ที่ต้องรอสะสมหลายเดือน จึงต้องเริ่มเก็บตั้งแต่วันนี้ ไม่ใช่ตอนจะใช้
--
-- ⚠️ **ไม่มีวันถูกกราฟหรือ LLM อ่านหรือเขียน** ทางเข้าทางเดียวคือ HR กรอกฟอร์มเอง
--
-- ⚠️ `result` ที่นี่ **คนละเรื่องกับ hr_decisions.decision** — อันนั้นตอบว่า "ให้ผ่านไป
-- สัมภาษณ์ไหม" (คำตัดสินคัดกรอง ที่ route_candidates อ่านไปตัดสินเส้นทางของกราฟ)
-- ส่วนอันนี้ตอบว่า "สัมภาษณ์แล้วเป็นยังไง" ถ้าเอาผลสัมภาษณ์ไปเขียนทับ hr_decisions
-- กราฟจะถูกปลุกให้ตัดสินใหม่โดยไม่มีใครสั่ง จากข้อมูลที่มันไม่เคยเห็น
--
-- ON DELETE CASCADE เหมือน hiring_stage (ข้อมูลระหว่างกระบวนการ) ไม่ใช่แบบ employees
-- ที่เป็น FK ธรรมดาเพื่อกันการลบ
CREATE TABLE IF NOT EXISTS interview_outcome (
    candidate_id UUID PRIMARY KEY REFERENCES candidates(id) ON DELETE CASCADE,
    result TEXT NOT NULL CHECK (result IN ('pass', 'fail', 'standby')),
    -- [{question, score, note}] โดย question อ้างอิงข้อความคำถามจาก interview_plan
    -- ช่วง score 1-5 บังคับที่ schemas.QuestionScore ไม่ใช่ที่ CHECK เพราะ Postgres
    -- ตรวจค่าข้างใน JSONB array ไม่ได้โดยไม่เขียน expression ที่ไม่มีใครอ่านออก
    question_scores JSONB,
    overall_note TEXT,
    -- วันที่สัมภาษณ์จริง ซึ่งมักไม่ใช่วันที่กรอกฟอร์ม จึงให้ HR ระบุเองแทนที่จะเดาจาก created_at
    interviewed_at DATE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- ============================================================
-- ข้อเสนอจ้างงาน (ขั้น "ยื่นข้อเสนอ" บนกระดาน) — หนึ่งแถวต่อผู้สมัคร
-- ============================================================
-- **แยกจาก hiring_stage โดยตั้งใจ**: hiring_stage เก็บแค่ขั้นล่าสุด พอย้ายไปขั้นอื่น (เช่นผู้สมัคร
-- ปฏิเสธข้อเสนอแล้วไป "ไม่ไปต่อ") ร่องรอยว่าเคยยื่นข้อเสนอก็หายไป ตารางนี้อยู่ต่อไม่ว่าขั้นจะ
-- เปลี่ยนเป็นอะไร ไทม์ไลน์จึงบอกได้ว่าเส้นทางหยุดหลังยื่นข้อเสนอ
--
-- ⚠️ **ไม่มีวันถูกกราฟหรือ LLM อ่านหรือเขียน** เหมือน interview_outcome — ทางเข้าคือ HR กรอกเอง
-- ⚠️ response='accepted' **ไม่ใช่การจ้าง** การจ้างคือแถวใน employees ซึ่งเกิดจากหน้าต่างรับเข้า
--    ที่ HR กดยืนยันเท่านั้น (ต้องกรอกข้อมูลจ้างและเป็นระเบียนถาวร)
-- ⚠️ salary เป็นข้อมูลอ่อนไหว — ห้ามใส่ใน URL หรือเขียนลง log
--
-- แก้ข้อเสนอ = เขียนทับแถวเดิม (เหมือน interview_outcome) ไม่ใช่ประวัติการต่อรองหลายรอบ
-- ON DELETE CASCADE เหมือน hiring_stage / interview_outcome (ข้อมูลระหว่างกระบวนการ)
CREATE TABLE IF NOT EXISTS job_offers (
    candidate_id UUID PRIMARY KEY REFERENCES candidates(id) ON DELETE CASCADE,
    position VARCHAR(255) NOT NULL,
    salary NUMERIC(12, 2) CHECK (salary IS NULL OR salary >= 0),
    start_date DATE,
    -- วันที่ผู้สมัครต้องตอบ — "เลยกำหนด" คำนวณฝั่งหน้าเว็บตามวันที่บนเครื่อง HR
    -- (backend ไม่รู้ว่าผู้ใช้อยู่โซนเวลาไหน)
    respond_by DATE,
    note TEXT,
    response VARCHAR(10) NOT NULL DEFAULT 'pending'
        CHECK (response IN ('pending', 'accepted', 'declined')),
    decline_reason TEXT,
    offered_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    responded_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- ============================================================
-- รูปโปรไฟล์ที่ดึงจากหน้าแรกของเรซูเม่ — หนึ่งแถวต่อผู้สมัคร (ไม่มีแถว = ไม่มีรูป)
-- ============================================================
-- ดึงตอนรับไฟล์เท่านั้น (app/resume_ingest.py) เพราะไบต์ PDF ไม่ถูกเก็บไว้ที่ไหนหลังจากนั้น
-- ผู้สมัครที่เข้ามาก่อนมีตารางนี้จึงไม่มีรูปตลอดไป และ reprocess ก็ดึงไม่ได้ (มีแค่ข้อความ)
-- — ข้อจำกัดชนิดเดียวกับ resume_sha256 ที่ backfill ไม่ได้
--
-- เลือกรูปด้วย heuristic ขนาด+สัดส่วน (app/resume_photo.py) ไม่มี face detection —
-- อาจหยิบโลโก้หรือกราฟิกมาแทนรูปคนได้ ยอมรับไว้ตั้งแต่ต้น
--
-- แยกตารางแทนคอลัมน์ใน candidates เพื่อไม่ให้ SELECT รายชื่อผู้สมัครลากไบต์รูปมาด้วย
-- ON DELETE CASCADE: ลบผู้สมัคร (อัปโหลดผิดไฟล์) รูปต้องหายไปด้วย
CREATE TABLE IF NOT EXISTS candidate_photos (
    candidate_id UUID PRIMARY KEY REFERENCES candidates(id) ON DELETE CASCADE,
    image_bytes BYTEA NOT NULL,
    content_type TEXT NOT NULL CHECK (content_type IN ('image/jpeg', 'image/png')),
    extracted_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- ============================================================
-- ไฟล์เรซูเม่ต้นฉบับ (PDF) — หนึ่งแถวต่อผู้สมัคร (ไม่มีแถว = ไม่มีไฟล์)
-- ============================================================
-- ให้ HR เปิดไฟล์จริงเทียบกับสิ่งที่ระบบอ่านได้ (ตัวอักษรไทยเพี้ยน ชื่อพิมพ์ผิด ทักษะที่เทียบไม่เจอ)
-- เก็บตอนรับไฟล์ใน app/resume_ingest.py เท่านั้น — ผู้สมัครที่เข้ามาก่อนมีตารางนี้จึงไม่มีไฟล์
-- ตลอดไป (ไบต์ไม่เคยถูกเก็บ) เหมือน candidate_photos และ resume_sha256
--
-- แยกตารางเพื่อไม่ให้ SELECT รายชื่อผู้สมัครลากไบต์ไฟล์มาด้วย
-- ON DELETE CASCADE: ลบผู้สมัครแล้วไฟล์ต้องหายไปด้วยเสมอ (ข้อมูลส่วนบุคคล)
-- ⚠️ ไฟล์มาจากคนนอก อาจฝังสคริปต์ — เสิร์ฟผ่าน endpoint ที่ต้องล็อกอิน ให้เบราว์เซอร์เปิดด้วย
--    ตัวดู PDF ของมันเอง ห้ามฝังลงในหน้าเว็บของเราตรง ๆ
CREATE TABLE IF NOT EXISTS candidate_files (
    candidate_id UUID PRIMARY KEY REFERENCES candidates(id) ON DELETE CASCADE,
    pdf_bytes BYTEA NOT NULL,
    filename TEXT,
    size_bytes INT NOT NULL,
    stored_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);
