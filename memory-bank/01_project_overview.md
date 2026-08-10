# Memory Bank — 01: ภาพรวมโปรเจค

> อ่านไฟล์นี้ก่อนเริ่มงานทุกครั้ง แล้วต่อด้วย `02_progress.md` (สถานะล่าสุด) และ `03_environment.md` (วิธีรัน)
> Source of truth ของสเปคคือโฟลเดอร์ [../brief/](../brief/) และ [../CLAUDE.md](../CLAUDE.md)

## โปรเจคคืออะไร
**TalentMatch AI** — ผู้ช่วย HR คัดกรอง resume แบบ multi-agent
HR อัปโหลด Job Description + ไฟล์ PDF resume หลายไฟล์ → ระบบ (LangGraph pipeline) แกะ JD และ resume,
ให้คะแนนความเหมาะสม (fit score), ตรวจอคติ (bias), แล้วแตกทางเป็น "ร่างคำถามสัมภาษณ์" หรือ "ร่างอีเมลปฏิเสธ"
โดยผู้สมัครที่คะแนนก้ำกึ่งจะ **หยุดกราฟรอให้ HR ตัดสินใจ (Human-in-the-Loop)**

## สถาปัตยกรรมหัวใจ (สรุปจาก CLAUDE.md)
- **One graph, one state:** `HRSystemState` (TypedDict) ส่งต่อทุกโหนด — นิยามเดียวที่ `app/agents/state.py`
- **ลำดับโหนดตายตัว:** `jd_analyzer → resume_parser → matcher → bias_auditor → route_candidates`
  - `resume_parser` ต้องคืน JSON รูปแบบเดียวกับ JD analyzer เพื่อให้ `matcher` ทำ gap analysis ได้
  - **Fit score ถ่วงน้ำหนัก:** required skills 60% + preferred skills 40%
- **Router (หัวใจของโปรดักต์)** หลัง bias_auditor:
  - `> 70` → ไป `interview_planner` อัตโนมัติ
  - `50–70` **และยังไม่มี HR decision** → หยุด (HITL)
  - `< 50` → `rejection_drafter`
- **HITL = resume ไม่ใช่ rerun:** compile กราฟด้วย checkpointer + `interrupt_before=["interview_planner"]`
  เมื่อ HR ตัดสินใจ → โหลด state เดิมด้วย `thread_id`, เขียน `hr_decision`/`hr_notes`, แล้วรันต่อจากจุด interrupt
  **ห้าม** rerun จาก entry point (เปลืองค่า LLM + เสีย context)
- **อัปโหลด resume แบบ async:** สกัด PDF ด้วย pdfplumber → เขียนแถวผู้สมัครทันที → เตะกราฟเป็น background task → ตอบกลับ; frontend poll เอา

## Stack
- **Backend:** Python 3.12, FastAPI + Uvicorn, LangGraph/LangChain, `langchain-google-genai`
  - LLM: Gemini 1.5 Flash (ดีฟอลต์), Pro เฉพาะขั้น matching/bias
  - Structured output: ทุกโหนดที่เรียก LLM ต้องมี Pydantic v2 model
- **DB:** Supabase Postgres — 4 ตารางแอป (`jobs`, `candidates`, `evaluations`, `hr_decisions`) + ตาราง checkpoint ของ LangGraph
  - Checkpointer: `PostgresSaver` จาก `langgraph-checkpoint-postgres`, เรียก `saver.setup()` ครั้งเดียว
  - `hr_decisions.candidate_id` เป็น UNIQUE (1 คน 1 ผล)
- **Vectors (optional):** ChromaDB (local) / pgvector (cloud), embeddings `models/text-embedding-004` 768 มิติ
- **Frontend (ยังไม่เริ่ม):** Next.js App Router + TS, ธีม dark glassmorphism (violet #8B5CF6), backend :8000 / frontend :3000

## ⚠️ ข้อจำกัดสำคัญของเครื่อง dev (ต้องรู้!)
เครื่องนี้เปิด **Windows Smart App Control (Enforcement)** ซึ่ง **บล็อก DLL ของ binary wheel ที่ไม่ได้เซ็นชื่อ/reputation ต่ำ**
- แพ็กเกจที่โดนบล็อกบน Windows venv: `psycopg[binary]` (libpq), `charset_normalizer` (mypyc)
- **ข้อสรุป: รัน/ทดสอบทุกอย่างใน Docker (Linux)** — SAC ไม่มีผลในคอนเทนเนอร์ ทุกแพ็กเกจทำงานปกติ
- `.venv` บน Windows เก็บไว้ให้ IDE ทำ autocomplete/type-check เท่านั้น (charset_normalizer ถูกแก้เป็น pure-python แล้ว; psycopg ยังบล็อกบน Windows แต่ไม่กระทบเพราะรันจริงใน Docker)
- **อย่าแนะนำให้ปิด Smart App Control** — ผู้ใช้เลือกทาง Docker แล้ว (การปิดเป็น one-way door ต้อง reset Windows)
