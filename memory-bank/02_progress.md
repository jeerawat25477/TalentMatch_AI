# Memory Bank — 02: ความคืบหน้า (สถานะล่าสุด)

> อัปเดตล่าสุด: 2026-08-30 (agent loop bias_auditor → matcher แบบ critique/revise) · แก้ไฟล์นี้ทุกครั้งที่ทำงานเสร็จเป็นก้อน

## ✅ เสร็จแล้ว

### สภาพแวดล้อม
- สร้าง `.venv` ด้วย **Python 3.12.10 (ตัวทางการจาก python.org ผ่าน winget)** ที่ root โปรเจค
  - เดิมลอง uv-managed 3.12/3.14 แต่ `_ssl`/binary DLL โดน Smart App Control บล็อก → เปลี่ยนมาตัวทางการ
- ติดตั้ง dependencies ครบใน `.venv` (import ผ่านหมดยกเว้น `psycopg` ที่โดน SAC บล็อกบน Windows — ไม่กระทบเพราะรันจริงใน Docker)
- แก้ `charset_normalizer` ในเวนv์ Windows เป็น pure-python (`--no-binary`)

### Docker (สภาพแวดล้อมรันจริง)
- [backend/Dockerfile](../backend/Dockerfile) — Python 3.12-slim, ติดตั้ง requirements, CMD `uvicorn app.main:app`
- [docker-compose.yml](../docker-compose.yml) — service `db` (postgres:16-alpine + healthcheck + volume `pgdata`) และ `backend` (build, depends_on db healthy, hot-reload, mount `./backend:/app`)
- [backend/.dockerignore](../backend/.dockerignore), [backend/.env.example](../backend/.env.example), [backend/.env](../backend/.env) (ค่าปัจจุบันเป็น placeholder — `GOOGLE_API_KEY=changeme`)
- **ทดสอบแล้ว:** ทุกแพ็กเกจ import ผ่านใน container รวม `psycopg` (libpq impl: binary); `PostgresSaver.setup()` สร้างตาราง checkpoint 4 ตารางได้

### Backend FastAPI + DB layer (เสร็จและทดสอบใน Docker แล้ว)
โครง `backend/app/`:
- [main.py](../backend/app/main.py) — FastAPI, CORS (allow `http://localhost:3000`), lifespan เรียก `init_db()`/`close_pool()`, `GET /health`
- [database.py](../backend/app/database.py) — psycopg `ConnectionPool` (dict_row) + `get_checkpointer()` (PostgresSaver, connection คงอยู่ตลอดอายุแอป) + `init_db()` (รัน schema.sql + saver.setup())
- [schema.sql](../backend/app/schema.sql) — DDL 4 ตาราง แบบ `CREATE TABLE IF NOT EXISTS`
- [schemas.py](../backend/app/schemas.py) — Pydantic v2: JobCreate/JobOut, CandidateSummary/Detail, ResumeUploadAccepted, HRDecisionIn/Out
- [utils/pdf_extractor.py](../backend/app/utils/pdf_extractor.py) — `extract_text_from_pdf(bytes) -> str`
- routers:
  - [jobs.py](../backend/app/routers/jobs.py) — `POST /api/v1/jobs`, `GET /api/v1/jobs/{id}`
  - [candidates.py](../backend/app/routers/candidates.py) — `POST /api/v1/jobs/{job_id}/resumes` (async, 202), `GET .../candidates` (เรียงตาม fit_score), `GET /api/v1/candidates/{id}`
  - [hr.py](../backend/app/routers/hr.py) — `POST /api/v1/candidates/{id}/decision` (upsert `ON CONFLICT (candidate_id)`)

**ผลทดสอบ integration (Docker):** /health ok · สร้าง/อ่าน job ได้ · list candidates · 404 เมื่อไม่พบ · upload non-PDF → 400 · HR decision candidate ไม่มี → 404 · ตารางใน DB ครบ 8 (แอป 4 + checkpoint 4)

### เลเยอร์ `app/agents/` — LangGraph (สร้างแล้ว, ทดสอบส่วนที่ไม่ใช้ LLM)
- [state.py](../backend/app/agents/state.py) — `HRSystemState` (คัดจากบรีฟ)
- [models.py](../backend/app/agents/models.py) — Pydantic: `JobRequirement, ResumeProfile, BiasAudit, InterviewPlan, EmailDraft`
- [llm.py](../backend/app/agents/llm.py) — `get_llm(complex)` → Gemini Flash/Pro (อ่าน `GOOGLE_API_KEY`)
- [nodes/](../backend/app/agents/nodes/) — 6 โหนด: jd_analyzer, resume_parser, matcher (deterministic, ไม่ใช้ LLM), bias_auditor (Pro), planner, drafter
- [graph.py](../backend/app/agents/graph.py) — `build_graph()` + `route_candidates` (3 ทาง) + `get_graph()` (singleton, compile ด้วย `get_checkpointer()` + `interrupt_before=["interview_planner"]`)
- [runner.py](../backend/app/agents/runner.py) — `process_candidate()` / `resume_after_decision()` : รันกราฟ + เขียนผลลง DB (นอกโหนด)
- **ความทนทานต่อ rate limit (เพิ่มภายหลัง):** ทุกโหนดเรียก LLM ผ่าน `llm.structured_invoke()` ที่มี **exponential backoff + jitter** (tenacity) — retry เฉพาะ error ชั่วคราว (429/503/timeout) ไม่ retry 404/auth; runner มี **semaphore จำกัด concurrency** (`GRAPH_MAX_CONCURRENCY` ดีฟอลต์ 2) กันหลาย upload ยิง LLM ชนเพดาน RPM พร้อมกัน
  - ⚠️ backoff แก้ได้แค่ลิมิต **ต่อนาที (RPM)** — ลิมิต **ต่อวัน (RPD=20)** retry ไปก็ไม่หาย ต้องสลับโมเดล/อัปเกรดแพลน
  - ทดสอบแล้ว (unit): 429→retry จนสำเร็จ, 404→ไม่ retry, 503→retry ครบ MAX_ATTEMPTS แล้ว reraise; และ `structured_invoke` เรียก Gemini จริงผ่าน
- เพิ่มคอลัมน์ `evaluations.interview_plan`, `evaluations.email_draft` (JSONB) + ALTER idempotent ใน [schema.sql](../backend/app/schema.sql)
- **เสียบเข้าเราเตอร์ครบ 3 จุด** (แทน TODO เดิม): jobs.create_job (analyze_jd, graceful), candidates background task (process_candidate), hr.submit_decision (resume_after_decision เป็น background task)

**ทดสอบแล้ว (ไม่ต้องใช้คีย์):** graph compile ครบ 6 โหนด · matcher: required 60%+preferred 40% (เคส 2/3+1/2 = 60 ✓) · router 3 ทางถูก · create_job graceful 201 แม้ LLM ล้ม · migrate คอลัมน์ใหม่สำเร็จ

### ✅ ทดสอบ end-to-end กับ Gemini จริงแล้ว (ผ่านทั้งหมด)
ใช้ [backend/sample_data/](../backend/sample_data/) — PDF 3 ใบที่ออกแบบให้ตกคนละแบนด์ + JD ที่ required=Python/FastAPI/PostgreSQL, preferred=Docker/LangGraph

| ผู้สมัคร | fit | เส้นทาง | ผลลัพธ์ที่ได้จริง |
| --- | --- | --- | --- |
| Somchai (strong) | 100 | auto-advance (>70) | 6 คำถาม + อีเมล `invitation` |
| Suda (mid) | 60 | หยุดรอ HR (50–70) → **approved** | ไม่มี plan/email จนกว่า HR ตัดสิน → หลัง approve ได้ 6 คำถาม + `invitation` |
| Suda (อัปโหลดซ้ำ) | 60 | หยุดรอ HR (50–70) → **rejected** | คำถาม = 0 (planner ถูก guard ข้าม) + อีเมล `rejection` ภาษาไทยสุภาพ |
| Anan (weak) | 0 | reject (<50) | อีเมล `rejection`, ไม่มีคำถาม |

- **JD Analyzer จริง:** Gemini สกัด required/preferred/min_experience ถูกครบ
- **Resume Parser จริง:** อัปเดต `full_name`/`email` จากชื่อไฟล์ placeholder เป็นค่าจริง; gap analysis แม่น (Suda ขาด PostgreSQL)
- **HITL พิสูจน์แล้วว่า resume ไม่ใช่ rerun:** นับ LLM call ตอน resume ได้ **2 ครั้งพอดี** (planner + drafter) ตอน approved และ **1 ครั้งพอดี** (drafter อย่างเดียว) ตอน rejected — ถ้า rerun จากต้นจะต้องเห็น resume_parser/bias_auditor ซ้ำเป็น 4+
- **guard ของ planner พิสูจน์แล้ว:** เคส rejected ใช้ LLM แค่ 1 call → planner ไม่ได้เรียก LLM เลยจริง
- **PostgresSaver พิสูจน์แล้ว:** backend restart ไปทั้งตัว แล้ว Suda ยัง resume ต่อจาก interrupt ได้ (ถ้าใช้ `SqliteSaver(":memory:")` ตามบรีฟจะพังตรงนี้)
- **background task ผ่าน API พิสูจน์แล้ว:** อัปโหลด → กราฟรันเบื้องหลัง → poll เห็นผล (ครบตามดีไซน์ async ใน CLAUDE.md)

### เลเยอร์ Frontend (Next.js MVP) — สร้างแล้ว, รันผ่าน Docker
- โครง `frontend/`: Next.js 14 App Router + TS + Tailwind + SWR; design token ที่ [../frontend/DESIGN.md](../frontend/DESIGN.md)
- 4 หน้า: home (list งาน), `jobs/new` (ฟอร์ม JD), `jobs/[id]` (dashboard: upload + ตาราง poll ทุก 4s + สถิติ), `jobs/[id]/candidates/[candidate_id]` (deep dive: ประวัติ + skill gap + คำถาม + อีเมลแก้ได้ + Approve/Reject)
- components: file-upload (drag-drop + progress), candidate-table, fit-score-bar, status-badge (Needs Review), skill-gap (รายการเขียว/แดง แทน radar ในรอบ MVP)
- backend เพิ่ม `GET /api/v1/jobs` (list + candidate_count) และ CORS อนุญาต :4000
- **ทดสอบแล้ว:** build image ผ่าน · ทุก route compile + render 200 (home, new, dashboard, deep dive) · `GET /jobs` คืน 3 งานถูกต้อง · ไม่มี error ใน log
- ⚠️ ยังไม่ได้คลิกทดสอบใน browser จริง (verify ด้วย compile 200 + API path) — ผู้ใช้ควรเปิด http://localhost:4000 ตรวจสายตาอีกรอบ
- **กับดัก port:** host 3000 อยู่ในช่วง reserved ของ Windows/WinNAT → ใช้ **4000** แทน (ดู 03)

### Redesign เป็นธีม "Luminous HR" (ตาม DESIGN.md ใหม่ + mockup)
ผู้ใช้เปลี่ยน [../frontend/DESIGN.md](../frontend/DESIGN.md) เป็นระบบใหม่ทั้งชุด — **ธีมสว่าง** (Trustworthy Blue `#0058be` บน `#f8f9ff`, Material-style tokens) แทนธีมมืดเดิม และให้อิง mockup ใน [../Design documentation shared/](../Design%20documentation%20shared/) (`uploads/Candidate.html` = deep dive, `Candidate List.dc.html` = หน้ารายชื่อ)
- `tailwind.config.ts` พอร์ต token ครบ (colors/spacing/borderRadius/fontSize headline-*, body-*, label-*)
- `globals.css`: พื้นหลัง gradient + `.glass-card` (Level 1) / `.glass-card-elevated` (Level 2) / `.ai-glow-border` / `pulse-soft`
- `layout.tsx` + `side-nav.tsx`: sidebar + topbar แบบ mockup, ฟอนต์ Inter + **Sarabun** (รองรับไทย), Material Symbols
- components ใหม่: `score-ring` (conic-gradient donut), `candidate-card` (การ์ดแทนตาราง), **`radar-chart`** (SVG จริงจาก `gap_analysis`), `ai-insight`; เลิกใช้ `candidate-table`/`fit-score-bar`
- dashboard เพิ่ม filter tabs + search + AI Insight (คำนวณจากข้อมูลจริง ไม่แต่งข้อความ)
- backend เพิ่ม `gap_analysis` เข้า `CandidateSummary` เพื่อโชว์ชิปทักษะบนการ์ด
- **สี radar ผ่านการตรวจ CVD แล้ว** (`#0058be` vs `#a36700` → ΔE 27 protan / 31 normal) + มี legend เสมอ

**ทดสอบด้วย headless screenshot จริง** (`msedge --headless --screenshot`) — ไม่ใช่แค่ status 200 เพราะหน้าเป็น client component ที่ SSR คืนแค่ "กำลังโหลด…"
- ✅ deep dive: radar แยกความต่างชัด (Suda ขาด PostgreSQL/LangGraph → รูปหลายเหลี่ยมเว้าเข้าศูนย์กลาง), bias panel, คำถาม, อีเมล, ปุ่ม HITL
- ✅ dashboard: stats/AI insight/tabs/การ์ด + score ring + ชิปเขียว-แดงถูกต้องทุกคน
### เฉลยแนวคำตอบในคำถามสัมภาษณ์ (brief §3.3 — เดิมข้ามไปตอน MVP)
- `models.py`: เพิ่ม `InterviewQuestion {question, expected_answer}` และ `InterviewPlan.questions` เปลี่ยนจาก `list[str]` → `list[InterviewQuestion]`
- `planner.py`: prompt สั่งให้ระบุแนวคำตอบ 2-4 ประเด็น เขียนให้ HR ที่ไม่เชี่ยวชาญสายงานตัดสินได้
- frontend: `components/interview-guide.tsx` (ใหม่) แสดงคำถาม + บล็อกเขียว "แนวคำตอบที่คาดหวัง"
- **รองรับข้อมูลเก่า:** แถวใน DB ก่อนหน้านี้เก็บ `questions` เป็น `string[]` → `normalizeQuestions()` ใน `lib/types.ts` แปลงให้เป็นรูปแบบเดียว (ของเก่าจะไม่มีแนวคำตอบ) ไม่ต้อง migrate DB
- **ทดสอบแล้ว:** เรียก planner ตรง ๆ ได้ 7 ข้อมี `expected_answer` ครบ · รันผ่านกราฟจริง (อัปโหลด → approve) ได้ผลเหมือนกัน · ดูภาพ UI ยืนยันว่าเรนเดอร์ถูก และเนื้อหาอิง gap analysis จริง (ข้อที่ถามทักษะที่ขาด แนวคำตอบบอกให้ดูว่าผู้สมัครมีแผนเรียนรู้ไหม)

### Sidebar หุบ/ขยาย (hamburger)
- `components/app-shell.tsx` (ใหม่, client) ถือ state ให้ sidebar/topbar/main ใช้ร่วมกัน — `layout.tsx` เป็น server component จึงถือ state เองไม่ได้
- **desktop:** หุบเป็นแถบไอคอน `w-16` ↔ ขยาย `w-64` (จำค่าไว้ใน localStorage `tm-sidebar-expanded`)
- **mobile:** เปิดเป็น drawer ซ้อน + backdrop, ปิดด้วย Esc / คลิกพื้นหลัง / เปลี่ยนหน้า (เดิมมือถือเข้าเมนูไม่ได้เลยเพราะ `hidden md:flex`)
- แก้ไอคอน active ที่เป็น `border-r-4` + `rounded-lg` แล้วโผล่เป็นขีดโค้งแปลก ๆ → เปลี่ยนเป็น `bg-primary/10`
- ครอบก้อนแสงพื้นหลังด้วย `fixed inset-0 overflow-hidden` (element แบบ fixed ไม่ถูกคลิปด้วย `body{overflow-x:hidden}`)
- ✓ **ยืนยัน mobile drawer แล้ว (2026-10-12)** — ตรวจทุกหน้าที่ 375px ในเบราว์เซอร์ของแอป: drawer เปิด/ปิด (Esc) ได้ · แก้ที่เจอ: หน้าต่างรับเข้าทำงานโดนเมนูทับ, ค้นหา/รับสมัครทางอีเมลล้นจอ, ปุ่มกรองแตกบรรทัด (ห้ามตัดคำ + "Needs Review" → "รอ HR" ทั้งระบบ), เส้นทางผู้สมัครเรียงแนวตั้งบนมือถือ · หน้าเข้าสู่ระบบตรวจแล้ว 2026-10-13 (ปิดตัวพิมพ์ใหญ่อัตโนมัติช่องชื่อผู้ใช้ + ปุ่มธีมทับการ์ดที่ 320×640) · ยังไม่ได้ตรวจ: เครื่องจริง (iOS Safari/คีย์บอร์ดบังช่อง)

- 🐛 **บั๊กที่เจอจากการดูภาพ:** ป้าย "Needs Review" ไม่มีพื้นหลัง เพราะ `tailwind.config.ts` ไม่ได้ scan `lib/` ทั้งที่ `BANDS` ใน `lib/types.ts` ถือคลาสสีอยู่ → **แก้แล้วโดยเพิ่ม `./lib/**/*.{ts,tsx}` ใน content** (บทเรียน: คลาส Tailwind ที่เขียนไว้นอก app//components/ จะไม่ถูก generate; และแก้ tailwind.config ต้อง restart container)

### แก้บั๊ก skill matching + เลเยอร์ vector (pgvector)

**บั๊กที่แก้:** `matcher._has()` เดิมเทียบ substring สองทาง (`n in o or o in n`) พิสูจน์กับข้อมูลจริงแล้วพบว่า
required `R` ถูกนับว่าตรงกับ `postgresql, docker, langgraph, redis` และ `ML` ตรงกับ `html`

- **`app/agents/skills.py` (ใหม่)** — รวมตรรกะเทียบทักษะไว้ที่เดียว
  - เทียบบน **ขอบเขตคำ (token)** ไม่ใช่ตัวอักษร → `"r"` ไม่มีทางโผล่ใน `"docker"` ได้อีก
  - `ALIASES` — สะกดต่างแต่คือตัวเดียวกัน (`NodeJs`/`Node.js`, `Postgres`/`PostgreSQL`, `k8s`)
  - `IMPLIES` — ครอบคลุมโดยปริยาย **ทางเดียว** (PostgreSQL ⟹ SQL แต่ SQL ⇏ PostgreSQL,
    React ⇏ React Native) เพื่อกู้เคสที่ substring เคยจับถูกโดยบังเอิญ
  - `is_skill()` — ตัดคำที่เป็นชื่อบทบาทคน (`product owners`, `engineers`) ที่ JD analyzer สกัดหลุดมา
    เดิมถูกนับเป็นตัวหาร กดคะแนนทุกคนลง
- **`matcher.py`** — เรียก `split_matched()` แทนตรรกะเดิม + **guard ใหม่**: ถ้า JD ไม่มีทักษะให้เทียบเลย
  บังคับคะแนน = 50 (แบนด์ HITL) เพราะสูตรเดิมจะให้ 100 ทุกคนแล้ว router auto-advance เชิญสัมภาษณ์ยกแผง
- **`jd_analyzer.py`** — prompt ห้ามใส่ชื่อตำแหน่งของคนที่ต้องร่วมงานลงใน skills (แก้ที่ต้นทาง)
- **`tests/test_skills.py` (ใหม่)** — 32 เทส ครอบเคสจากข้อมูลจริงใน DB
- **`scripts/recompute_scores.py` (ใหม่)** — คำนวณคะแนนเดิมใหม่ **โดยไม่เรียก LLM** + ล้าง role nouns
  ออกจาก `jobs.parsed_criteria` (ไม่งั้น dashboard ยังโชว์ชิป "product owners" ทั้งที่ไม่ถูกนับ)
  - ผลจริง: AI Engineer — Somchai 3→46, Anan 3→40, Suda 0→40 (ตัวหารเดิมมี role noun ปน 5 คำ)

**⚠️ เลเยอร์ vector แก้ปัญหา skill matching ไม่ได้ — วัดแล้ว** (CLAUDE.md เดิมเขียนว่าแก้ได้ ไม่จริง)
cosine ของ `gemini-embedding-001`: PostgreSQL↔MySQL **0.885**, Java↔JavaScript **0.865**,
R↔React **0.845** — ทั้งหมด *สูงกว่า* คู่ที่ควรตรงจริงอย่าง React Native↔Mobile Hybrid (**0.838**)
→ ไม่มี threshold ใดแยกได้ ตั้งที่ 0.83 เพื่อรับ React Native ก็จะรับ MySQL ว่าเป็น PostgreSQL ด้วย
จึงใช้ embeddings เฉพาะงาน **จัดอันดับให้มนุษย์ดู** ตาม brief §1.2 เท่านั้น

- **`app/vectors.py` (ใหม่)** — pgvector (ไม่ใช่ Chroma: มี Postgres อยู่แล้ว, join กับ candidates ได้ตรง,
  ไม่ต้องลง `chromadb` ที่ลาก onnxruntime มาทั้งก้อน) ใช้ retry/backoff ชุดเดียวกับ `llm.py`
- **โมเดล:** บรีฟระบุ `models/text-embedding-004` — **คีย์ปัจจุบันเรียกไม่ได้แล้ว** (ไม่อยู่ใน ListModels)
  ใช้ `gemini-embedding-001` ที่คืน 3072 มิติ แต่ตั้ง `output_dimensionality=768` ได้ (Matryoshka)
  จึงคงคอลัมน์ `VECTOR(768)` ตาม CLAUDE.md ได้ · โควตา embedding **แยกจาก** generateContent
- **`docker-compose.yml`** — `postgres:16-alpine` → `pgvector/pgvector:pg16`
  ⚠️ volume เดิม initdb ด้วย alpine (musl) อิมเมจใหม่เป็น Debian (glibc) — **PG 16 เท่ากันจึงอ่านได้
  ทดสอบแล้วข้อมูลครบ** แต่ทำ `pg_dump` สำรองก่อนเสมอ
- **`schema.sql`** — `CREATE EXTENSION vector` + `resume_embeddings` (`candidate_id UNIQUE` เพื่อ upsert)
  + HNSW index (`vector_cosine_ops`)
- **`runner.py`** — index หลัง `_persist_evaluation()` ใน try/except (index ล้มต้องไม่ทำให้กราฟพัง)
- **`GET /api/v1/candidates/search?q=&limit=`** — ⚠️ ต้องประกาศ **ก่อน** `/candidates/{candidate_id}`
  ไม่งั้น FastAPI จับ `"search"` เป็น candidate_id แล้วตอบ 404
- **dedupe:** 1 คนมีหลายแถวได้ (candidates ผูกกับ job — สมัคร 5 ตำแหน่ง = 5 แถว) ผลค้นหาเลยซ้ำ 5 บรรทัด
  แก้ด้วย `DISTINCT ON (re.content)` เลือกแถวที่ `parsed_resume` ไม่ NULL (ชื่อจริง ไม่ใช่ชื่อไฟล์)
- **frontend:** `app/search/page.tsx` (รองรับ `?q=` เพื่อแชร์ลิงก์/ตรวจด้วย screenshot ได้) + เมนูใน side-nav

**ทดสอบแล้ว:** 32 เทสผ่าน · backfill 19/19 · ค้น "นักออกแบบกราฟิกและงานดีไซน์เว็บ" → Anan
(Photoshop/Illustrator/Figma) มาที่ 1 ส่วน "วิศวกรหลังบ้านที่ทำฐานข้อมูลและ API" → Somchai มาที่ 1
**อันดับกลับด้านสนิทระหว่างสองคำค้น และ query เป็นไทยแต่ resume เป็นอังกฤษ — พิสูจน์ว่าเป็น semantic จริง
ไม่ใช่การจับคำ** · ตรวจ UI ด้วย headless screenshot ทั้งหน้า search และ dashboard

### ตรวจ Router / State Machine แล้วแก้บั๊ก HITL

**🔴 บั๊กหลักที่เจอ:** `resume_after_decision` เดิม `update_state()` + `invoke(None)` เฉย ๆ
ซึ่งได้ผลเฉพาะตอนกราฟ **ค้างอยู่ที่ interrupt** เท่านั้น ตรวจ state จริงทั้ง 15 คนพบว่า
**มีแค่ 1 คนที่ปุ่มใช้งานได้** ที่เหลือกราฟจบไปแล้ว → กดปุ่มแล้ว **ไม่มีอะไรเกิดขึ้นเลย**
แต่ API ตอบ 200 และหน้าเว็บขึ้นว่า "กำลังสร้างผลลัพธ์ต่อ…" (พิสูจน์แล้วด้วยการรันจริง:
`next` ว่าง → `invoke(None)` ไม่ปลุกโหนดใด → plan/mail ไม่เปลี่ยน)
เคสที่เจ็บที่สุดคือ `fit < 50` ซึ่ง**ไม่เคยแวะ interrupt เลย** → HR กู้คนที่ AI ตัดผิดไม่ได้ตลอดกาล

**การแก้:**
- `route_candidates` ดู `hr_decision` **ก่อน** คะแนนเสมอ — เป็นจุดที่ทำให้ "มนุษย์มีอำนาจสูงสุด" เป็นจริง
- `resume_after_decision` แยกสองเคส: ค้างที่ interrupt → เดินต่อตามเดิม · **จบแล้ว → ย้อน state
  ด้วย `update_state(..., as_node="bias_auditor")`** ให้ router ตัดสินใหม่โดยมีคำตัดสิน HR อยู่ในมือ
- `_drive_to_end()` — ต้อง `invoke` ซ้ำ เพราะการย้อน state ทำให้เดินมาถึง `interview_planner`
  แบบสด ๆ (ไม่ใช่ resume) `interrupt_before` จึงทำงานอีกรอบ invoke ครั้งเดียวไม่พอ
- `_persist_outputs` ล้าง `interview_plan` เมื่ออีเมลเป็น rejection — เพราะ state สะสมข้ามรอบ
  ถ้า HR กลับคำเป็นปฏิเสธ เส้นทาง reject ไม่แวะ planner คำถามรอบเก่าจะค้างคู่กับอีเมลปฏิเสธ
- `drafter` ก็ดู `hr_decision` ก่อนคะแนน (ไม่งั้น HR อนุมัติคนคะแนนต่ำจะได้คำถามสัมภาษณ์
  คู่กับอีเมล**ปฏิเสธ**)
- **`app/agents/bands.py` (ใหม่)** — เลข 50/70 เคยกระจาย 6 ที่ (graph, runner, drafter, matcher,
  recompute_scores, frontend) ย้ายมารวมที่เดียว เหลือสำเนาเดียวที่ `frontend/lib/types.ts` (มีคอมเมนต์เตือน)
- **`CandidateDetail.graph_status`** (`awaiting_hr` | `completed` | `processing`) + หน้า deep dive
  บอกตรง ๆ ว่าการกดปุ่มจะ "เดินต่อ" หรือ "ทับผลเดิม" แทนข้อความเดิมที่บอกว่าสำเร็จทุกกรณี

**ทดสอบแล้ว** (stub `structured_invoke` เพราะโควตา Gemini รายวันหมด — ตรวจเฉพาะ state machine):

| เคส | ก่อน | หลัง | โหนดที่รัน |
| --- | --- | --- | --- |
| fit=0 auto-reject → HR **approved** | mail=rejection, คำถาม=0 | mail=**invitation**, คำถาม=1 | planner + drafter |
| fit=100 auto-pass → HR **rejected** | mail=invitation, คำถาม=6 | mail=**rejection**, คำถาม=**0** | drafter อย่างเดียว |
| fit=70 ค้างที่ interrupt → approved (regression) | awaiting_hr | mail=invitation, คำถาม=1 | planner + drafter |

แถวที่ 3 ยืนยันว่า **ไม่ได้ rerun จากต้น** (2 call ไม่ใช่ 4+) — invariant ใน CLAUDE.md ยังอยู่ครบ

> ⚠️ ข้อมูลทดสอบ: อีเมลของ Anan (fit=0) กับ Somchai (fit=100) 2 แถวถูกทับด้วยเนื้อหาปลอม
> (`subject="s"`, `body="b"`) จาก stub — อัปโหลด resume ใหม่ทับได้เมื่อโควตากลับมา
>
> อัปเดต 2026-09-02: จริง ๆ มี **3 แถว** (Suda ด้วย) — 2 แถวหายไปพร้อม job `3d43035d…` ตอนเก็บกวาด
> เหลือของ Anan ในงาน `29270baa…` แถวเดียว ยังไม่ล้าง (ไม่เคยส่งออกจริง `email_sent_at` ว่าง)

### ส่งอีเมลจริง (SMTP) + แก้ช่องโหว่ใกล้ตัว + รายงาน security
- **ส่งอีเมลได้จริงแล้ว** — `POST /api/v1/candidates/{id}/email/send` (synchronous: HR ต้องรู้ทันทีว่าสำเร็จ/ล้ม)
  - `app/email_sender.py` (ใหม่): smtplib + `EmailMessage` · dev ส่งเข้า **MailHog** (`mailhog:1025`, UI :8025)
    prod override `SMTP_*` เป็น SMTP จริง (เช่น Gmail app password)
  - schema เพิ่ม `evaluations.email_sent_at`, `email_sent_to` (กันส่งซ้ำ + audit)
  - frontend: การ์ดร่างอีเมลมี input ผู้รับ + หัวข้อ + เนื้อความ (แก้ได้ทั้งหมด) + ปุ่มส่ง + ป้าย "ส่งแล้ว" + "ส่งซ้ำ" (ยืนยันก่อน)
- **แก้ช่องโหว่ (บันเดิลกับ SMTP/upload)** — ดูเต็มใน [04_security.md](04_security.md):
  - **spam relay:** ผู้รับมาจากอีเมลที่ LLM แกะจาก PDF → ให้ HR ยืนยันผู้รับเองบน UI + validate `EmailStr` + log ทุกการส่ง
  - **header injection:** `EmailMessage` + `_clean_header()` ตัด CRLF → ทดสอบแล้ว Bcc ไม่รั่ว
  - **upload DoS:** จำกัด `MAX_UPLOAD_MB` (10) / `MAX_FILES` (20) + ตรวจ magic bytes `%PDF-` + try/except รอบ pdfplumber
  - เพิ่ม **`.gitignore`** ที่ root (กัน `.env` รั่วก่อน `git init`) — เดิมยังไม่มี
- **ทดสอบแล้ว:** ส่งปกติ→200 เข้า MailHog · header injection→Bcc ว่าง · อีเมลผิดรูป→422 · fake pdf→400 · ไฟล์>10MB→413 ·
  32 เทสเดิมผ่าน · ไม่มี error ใน log · headless screenshot ยืนยันป้าย "ส่งแล้ว" + ปุ่ม "ส่งซ้ำ"

### Authentication (ล็อกอิน username/password + JWT) — ปิดช่องโหว่ 🔴 อันดับ 1
- **backend:**
  - ตาราง `users` (bcrypt hash) · `app/auth.py`: hash/verify + JWT HS256 + `get_current_user` (dependency) + `seed_admin()` + rate-limit login (in-memory, 5 fail/5 นาที → 429)
  - `app/routers/auth.py`: `POST /api/v1/auth/login` → JWT · `GET /api/v1/auth/me`
  - กันทุก router (jobs/candidates/hr) ด้วย `dependencies=[Depends(get_current_user)]` ระดับ router — เปิดไว้แค่ `/health` + `/auth/login`
  - `JWT_SECRET` **ไม่มีดีฟอลต์ในโค้ด** (secret ที่ hardcode = ปลอม token ได้) · seed admin จาก env ใน `init_db()`
- **frontend:**
  - `lib/auth.ts` เก็บ token ใน localStorage · `lib/api.ts` แนบ `Authorization` ทุก request + เจอ 401 → clear + เด้ง `/login` (ครอบทั้งแอปเพราะ SWR ใช้ `request`)
  - `app/login/page.tsx` (ใหม่) · `app-shell.tsx` guard (ไม่มี token → เด้ง login, ซ่อน chrome ที่ `/login`) + topbar โชว์ username จริง + ปุ่มออกจากระบบ
- **ทดสอบแล้ว:** ไม่มี token→401 · `/health` เปิด→200 · login ถูก→200+token · มี token→200 · `/me`→`admin` · รหัสผิด→401 · ผิด 5 ครั้ง→**429** · 39 เทสผ่าน (32 เดิม + 7 auth) · headless screenshot: เปิด `/` ไม่มี token **เด้งไป login เอง** (guard ทำงาน) + หน้า login เรนเดอร์ถูก
- **dev creds:** `admin` / `admin1234` (ตั้งใน docker-compose — เปลี่ยนก่อนใช้จริง)

### LangSmith tracing — เปิดใช้แล้ว (env-driven)
- **กลไก:** LangChain/LangGraph มี tracing ในตัว — ตั้ง `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY`
  ใน `backend/.env` แล้ว trace เปิดเอง (ไม่มีโค้ดสลับ) · ไม่มีคีย์ = no-op รันปกติ · SDK รับทั้ง `LANGCHAIN_*`/`LANGSMITH_*`
- **โค้ดที่เพิ่ม (แค่ทำให้ใช้ได้จริง ไม่ใช่เปิด/ปิด):**
  - `runner._config` ติดป้าย `run_name=screen-candidate-<id8>`, `tags=["talentmatch","screening"]`,
    `metadata.candidate_id` → หา trace ของแต่ละคนใน LangSmith เจอ
  - `app/tracing.py::tracing_status()` + log ตอนบูตว่าเปิด/ปิด + project (ยืนยัน env ถูกอ่าน)
- **ทดสอบแล้ว:** log ตอนบูตขึ้น **"LangSmith tracing เปิดอยู่ → project=talentmatch-ai"** (คีย์ถูกอ่านจริง) ·
  ยิง `/candidates/search` (embeddings = **โควตาแยกจาก chat** ที่หมดรายวัน) สำเร็จ 200 → trace ถูกส่ง ·
  39 เทสผ่าน · ไม่มี error
  - ⚠️ ยืนยัน trace ขึ้น LangSmith UI จริงต้องให้ผู้ใช้เปิดดูเอง (ผมเห็น UI ไม่ได้) หรือให้ผมเรียก
    LangSmith API ด้วยคีย์ใน `.env` เพื่อ list run (ต้องขออนุญาตก่อน) · trace ของกราฟเต็ม 6 โหนดจะเห็นเมื่อโควตา chat กลับมา

### RAG — retrieval agent หาผู้สมัครคล้ายกัน (เปิด/ปิดได้)
ต่อยอด "multi-agent" — เพิ่มโหนด `retrieve_similar` ([nodes/retriever.py](../backend/app/agents/nodes/retriever.py))
วางระหว่าง `resume_parser` → `matcher`
- **เปิด/ปิดด้วย `RAG_ENABLED`** (env) — ปิด = โหนด no-op กราฟรันเหมือนเดิม (พิสูจน์แล้วในคอนเทนเนอร์จริง)
- เปิด → ค้น pgvector ด้วยทักษะที่ parser แกะได้ `vectors.search(..., exclude_candidate_id=cid)` (กันเจอตัวเอง)
- **คุณค่าจริง (ไม่ใช่คะแนนแม่นขึ้น):** (1) HR เห็นบริบทเทียบเคียง (2) `planner` เอาไปตั้งคำถามเจาะขึ้น
  — **ไม่เพิ่ม chat call** เพราะ planner ยิง LLM อยู่แล้ว + retrieval ใช้ embedding quota แยก
- เก็บที่ `evaluations.similar_candidates` (JSONB) · โชว์การ์ด "ผู้สมัครที่โปรไฟล์คล้ายกัน" ในหน้า deep dive
- **ทดสอบแล้ว:** 43 เทสผ่าน (39 เดิม + 4 retriever: toggle off no-op / ส่ง query+exclude ถูก / ไม่มีทักษะ→ว่าง / search พังแล้ว swallow) ·
  รันจริงผ่าน API: อัปโหลด resume → log "เจอคนคล้าย 3 คน" → API คืน 3 คนเรียงตาม distance **และ self ไม่อยู่ในลิสต์** ·
  โหนด `retrieve_similar` โผล่ในกราฟ · toggle off (รันโหนดตรง ๆ ด้วย RAG_ENABLED=false) → similar ว่าง
  - ⚠️ การ์ดบนหน้าเว็บ **ยังไม่ได้ screenshot** (headless inject token cross-origin ไม่ได้) — ยืนยันผ่าน API + หน้า compile ผ่าน; ผู้ใช้เปิดดูเองได้

### วงจรชีวิตตำแหน่งงาน — ปิดรับสมัคร (status) + ลบถาวร
แยกสอง use case ที่ HR ขอมาเป็นคนละปุ่ม เพราะผลลัพธ์ต่างกันสิ้นเชิง
- **`jobs.status` = `open | closed`** (+ `closed_at`) เพิ่มด้วย `ALTER TABLE ... IF NOT EXISTS` ตาม pattern เดิม —
  งานเดิม 6 ตำแหน่งกลายเป็น `open` อัตโนมัติ ไม่ต้อง backfill
- **`PATCH /api/v1/jobs/{id}`** เปิด/ปิดรับสมัคร = ทางเลือกแทนการลบเมื่อรับพนักงานได้แล้ว —
  ปิดแล้ว `upload_resumes` ตอบ 409 แต่ผู้สมัคร/คะแนน/หลักฐานอีเมล/เวกเตอร์ยังอยู่ครบ
- **`DELETE /api/v1/jobs/{id}`** สำหรับงานที่สร้างผิด มีการ์ด 2 ชั้นใน `jobs.py::_deletion_blocker`:
  (1) เคยส่งอีเมลแล้ว → 409 ถาวร (หลักฐาน audit ลบไม่ได้) (2) กราฟกำลังรัน → 409 ชั่วคราว
  ผ่านทะเบียนใหม่ `runner.active_candidates()` (เซ็ตในโปรเซส + lock, ลงทะเบียนก่อนเข้าคิว `_gate`)
- **checkpoint ของ LangGraph ไม่มี FK** → เก็บ `candidate_id` ไว้ก่อน cascade แล้วเรียก
  `PostgresSaver.delete_thread` **หลัง** commit (ถ้าทำก่อนแล้ว DELETE พังจะทำลาย HITL ของงานที่ยังอยู่)
- **UI:** แท็บกรอง ทั้งหมด/เปิดรับ/ปิดแล้ว บนหน้ารายการ · เมนู `⋯` บนการ์ด (วางเป็น *พี่น้อง* ของ `<Link>` ไม่ใช่ลูก — กันปุ่มซ้อนลิงก์) ·
  `components/confirm-dialog.tsx` ตัวแรกของโปรเจกต์ (แทน `window.confirm`) บังคับพิมพ์ชื่อตำแหน่งถ้ามีผู้สมัครติดไปด้วย · `.btn-danger` ใน globals.css
- **ทดสอบแล้ว:** 49 เทสผ่าน (45 เดิม + 4 `test_jobs_guard.py`) · ยิง API จริงครบทุกกิ่ง —
  PATCH closed → `closed_at` มีค่า, upload เข้างานที่ปิด → 409, PATCH open → `closed_at` = NULL,
  DELETE งานว่าง → 200, DELETE ซ้ำ → 404, DELETE ระหว่างกราฟรัน → 409 "กำลังประมวลผล",
  DELETE งานที่มีผู้สมัคร 1 คน → `deleted_candidates:1, deleted_threads:1` และ checkpoint 7 แถวของ thread นั้นหายเกลี้ยง
  - หมายเหตุ: ~~ยังมี orphan checkpoint 5 แถวของ thread `566187c1…`~~ — **ลบแล้ว 2026-09-02** (ดู "เก็บกวาดข้อมูล dev" ด้านล่าง)

### กู้เคสผู้สมัคร "วิเคราะห์ค้าง" (ปุ่มวิเคราะห์ใหม่ + ป้ายค้าง)
พบของจริง: ผู้สมัคร 4 คนค้างเป็น "กำลังวิเคราะห์…" มาตั้งแต่ **21 ก.ค.** (12 วัน) มี checkpoint คนละ 3 แถว
= กราฟเริ่มแล้วตายกลางทาง แล้วไม่มีอะไรมารันต่อ
- **สาเหตุราก:** `BackgroundTasks` อยู่ในโปรเซส — container รีสตาร์ต/hot-reload/โควตาหมด งานหายทันที ไม่มี retry
  และ UI แปล "ไม่มีคะแนน" เป็น `pending` = "กำลังวิเคราะห์…" **ตลอดกาล** ซึ่งเป็นการโกหก HR
- **`_is_stalled`** ([candidates.py](../backend/app/routers/candidates.py)): ไม่มี evaluation + ไม่อยู่ใน `active_candidates()` +
  เก่ากว่า `STALLED_AFTER_SEC` (90) → `stalled=true` บน `CandidateSummary`/`CandidateDetail`
- **`POST /api/v1/candidates/{id}/reprocess`** — รันใหม่จาก `raw_resume_text` ใน DB ไม่ต้องอัปโหลด PDF ซ้ำ ·
  409 ถ้ามีผลแล้ว (กันเปลืองโควตา + กันทับผล HITL) หรือกำลังรันอยู่ · 422 ถ้าสกัดข้อความจาก PDF ไม่ได้เลย
- **แก้ช่องโหว่ของทะเบียนที่เพิ่งทำ:** เดิม `_run_graph_for_job` จองทีละคนตอนถึงคิว → คนที่ 3-20 ของ batch
  จะดู "ตายแล้ว" ทั้งที่รอคิวอยู่ (และการ์ดกันลบก็มองไม่เห็นเขา) → เปลี่ยนเป็น `reserve_candidates()` ทั้ง batch ตั้งแต่ต้น
- **ทดสอบแล้ว:** 54 เทสผ่าน (49 + 5 `test_stalled.py`) · API จริง: 3 คนขึ้น `stalled=true` ·
  กด reprocess → 202 · กดซ้ำทันที → 409 · ผ่านไป ~40 วิ `strong_somchai` → **`Somchai Jaidee` fit=17, stalled=false**
  - **ต้นทุนจริงที่วัดได้: 3 chat call ต่อคน** (resume_parser + bias_auditor + drafter) — checkpoint เดิม
    **ไม่ได้ช่วยประหยัด** เพราะเคสที่ค้างตายตั้งแต่โหนดแรก ๆ (อย่าเชื่อสมมติฐาน "resume แล้วประหยัด")
  - ยังเหลือค้างอีก 3 คน (weak_anan, mid_suda, +1 ในงาน Senior Python Developer) — กดจากหน้าเว็บได้เลย

### ลบผู้สมัครรายคน (อัปผิดไฟล์ / อัปซ้ำ)
พบของจริงจากหน้าเว็บ: `Suda Rakdee` โผล่ 4 แถวในงานเดียว — ตรวจ DB แล้ว **ผู้สมัคร 20 แถว มีเรซูเม่จริงแค่ 3 ฉบับ**
(นับจาก `md5(raw_resume_text)`) เพราะเป็นไฟล์ทดสอบที่อัปซ้ำหลายรอบ
- **`DELETE /api/v1/candidates/{id}`** — cascade แคบ กระทบเฉพาะ evaluations/hr_decisions/resume_embeddings ของคนเดียว ·
  การ์ดเดียวกับการลบงาน (`_candidate_deletion_blocker`): ส่งอีเมลแล้ว → 409 ถาวร, กำลังวิเคราะห์ → 409 ชั่วคราว ·
  `delete_thread` หลัง commit เหมือนเดิม
- **UI:** ปุ่มถังขยะบน `CandidateCard` + `ConfirmDialog` (ไม่บังคับพิมพ์ชื่อ เพราะขอบเขตแคบและต้องกดหลายครั้งตอนเคลียร์ของซ้ำ) ·
  prop `onRetried` เปลี่ยนชื่อเป็น `onChanged` ใช้ร่วมกับปุ่มวิเคราะห์ใหม่
- **ทดสอบแล้ว:** 58 เทสผ่าน (54 + 4) · API จริง: ลบคนที่ส่งอีเมลแล้ว → 409 ·
  ลบตัวซ้ำ → 200 `deleted_thread:true` และ checkpoint 7/eval 1/embedding 1 → **0 ทั้งหมด** · ลบซ้ำ → 404
  - ⚠️ ระหว่างทดสอบ **ลบ Suda Rakdee ตัวซ้ำไป 1 แถว** (`eb301659…`) — เป็นข้อมูลทดสอบ ผู้ใช้รับทราบแล้ว
- **ยังไม่ได้ทำ (รู้แล้วแต่เลือกยังไม่ทำ):** ไม่มีการกันอัปซ้ำที่ต้นทาง — อัป PDF เดิมซ้ำยังสร้างผู้สมัครใหม่
  + รันกราฟใหม่ (3 chat call ทิ้ง) ได้เรื่อย ๆ และเพราะ `email_sent_at` อยู่บน `evaluations` (ต่อแถว ไม่ใช่ต่อคน)
  HR อาจส่งอีเมลซ้ำหาคนเดียวกันโดยไม่เห็นคำเตือน · ทางแก้ที่เสนอไว้: เทียบ hash ของข้อความกับผู้สมัครเดิมในงานนั้นตอนอัปโหลด
- **ตรวจแล้วว่าไม่เสียหาย:** คลัง RAG ไม่ได้เพี้ยนจากตัวซ้ำ — [vectors.py](../backend/app/vectors.py) มี `DISTINCT ON (re.content)` อยู่แล้ว
  (ยิงค้นจริงคืน 3 คน ไม่ใช่ 8) อย่าเอาข้อนี้ไปเป็นเหตุผลของงานถัดไป

### Agent loop: bias_auditor → matcher (critique → revise) — จำกัด 1 รอบ
ทำให้ระบบเป็น multi-agent orchestration มากขึ้นจากเดิมที่ auditor แค่ตรวจแล้วส่งต่อ
- **`BiasAudit` structured output** เพิ่ม `biased_required_skills` / `biased_preferred_skills` ให้ auditor ระบุ skill criteria จาก JD ที่ควรถอดเพราะอาจมีอคติ
- **state ใหม่:** `bias_revision_count`, `bias_revision_pending`, `bias_exclusions`
  - auditor flag + มี criteria ให้ถอด + ยังไม่เคย revise → set pending และนับรอบ
  - matcher อ่าน `bias_exclusions` แล้วกรอง JD ก่อนคำนวณคะแนนใหม่แบบ deterministic
  - matcher clear pending แล้วส่งกลับ auditor ตรวจซ้ำอีกครั้ง
- **graph:** conditional edge หลัง `bias_auditor` เพิ่มทาง `revise → matcher`; HR decision ยังชนะก่อนเสมอ (`approved/rejected` ไม่ถูก loop ขวาง)
- **คุมโควตา:** เพิ่ม chat call เฉพาะเคส flagged เท่านั้น และวนได้สูงสุด 1 รอบ (`MAX_BIAS_REVISIONS = 1`)
- **เก็บร่องรอย + โชว์บนหน้าเว็บ:** คอลัมน์ใหม่ `evaluations.bias_revision` (JSONB) เก็บ
  `{round, score_before, score_after, excluded_required, excluded_preferred, reason}` — **matcher เป็นคนเขียน**
  (มันรู้คะแนนก่อน/หลัง) แล้ว auditor รอบสองคัดลอกต่อไปถึง `_persist_evaluation`
  - เดิม codex ต่อข้อความ "Revise รอบที่ 1" ลง `audit_log` แต่ auditor **รอบสองเขียนทับทั้งช่อง** → ลูปหายไปจากหน้าเว็บทั้งดุ้น (ถอดออกแล้ว)
  - หน้า detail ผู้สมัครมีการ์ดสีอำพัน "ตรวจอคติแล้วให้คำนวณคะแนนใหม่ N รอบ — ถอดเกณฑ์ … / คะแนน X → Y"
- **ทดสอบแล้ว:** `test_bias_loop.py` 5 เคส — auditor ตั้ง pending, matcher apply exclusion, ไม่วนเกิน 1,
  HR decision ชนะ pending revision, และเส้นทางเต็ม matcher→auditor→router→matcher→auditor ที่ยืนยันว่า
  `bias_revision` รอดไปถึง evaluation สุดท้าย (ยังไม่ได้รันชุดเต็มใน Docker — Docker daemon ปิดอยู่ตอนแก้)

### Bias Auditor เห็น JD ต้นฉบับ — เตือนอคติที่ "ถอดออกจากคะแนนไม่ได้"
**สิ่งที่พบตอน smoke test ลูป bias ด้วย Gemini จริง (2026-09-01) — สำคัญ:**
`jd_analyzer` **กรองเกณฑ์อคติทิ้งตั้งแต่ node แรก** (prompt บังคับว่า required/preferred_skills
ใส่ได้เฉพาะ "สิ่งที่ผู้สมัครทำเป็น") ทดสอบ 2 ใบ:
- "จบจากมหาวิทยาลัยชั้นนำเท่านั้น" → ไปโผล่ที่ฟิลด์ `education` ไม่เข้า `required_skills`
- "เพศชาย อายุไม่เกิน 30 ปี" → **หายไปเลย** ไม่อยู่ในผลสกัดเลยสักช่อง

→ **ลูปถอด skill แทบไม่มีทาง trigger จาก JD ปกติ** เพราะของที่ควรถอดไม่เคยเดินทางไปถึง
`required_skills` เก็บลูปไว้ในฐานะ "ตาข่ายชั้นสอง" (jd_analyzer เคยปล่อยของที่ไม่ใช่ทักษะหลุดมาแล้ว
จนต้องมี `is_skill()`) ต้นทุนตอนไม่ทำงาน = 0 — **อย่าเข้าใจผิดว่านี่คือกลไกกันอคติหลัก**

**กลไกที่กันอคติได้จริงคือตัวนี้:** `bias_auditor` ตอนนี้รับ `raw_jd` (ตัดที่ 4000 ตัวอักษร) +
`education` + `min_experience_years` เข้า prompt (เดิมเห็นแค่ `required_skills`/`gaps` ที่ถูกล้าง
มาแล้ว จึงตาบอดกับอคติในประกาศโดยสิ้นเชิง) แล้วคืน `BiasAudit.biased_jd_criteria` ซึ่งถูกต่อท้าย
`audit_log` เป็นบรรทัด "⚠ เกณฑ์ใน JD ที่อาจมีอคติ (ไม่ได้ถูกใช้คิดคะแนน — ควรแก้ประกาศ): …"
ขึ้นบนการ์ดเดิมในหน้า detail — ไม่ต้องเพิ่มคอลัมน์/หน้าจอใหม่
- **ทดสอบ e2e จริงแล้ว:** JD ที่มี "เพศชาย อายุไม่เกิน 30 ปี" + `mid_suda.pdf` → `audit_status=flagged`,
  audit_log มีบรรทัดเตือนพร้อมเกณฑ์ทั้งสองข้อ, `bias_revision` เป็น NULL (ไม่มีอะไรให้คำนวณใหม่
  จึง **ไม่วนลูปเสีย chat call ฟรี ๆ** = พฤติกรรมที่ต้องการ) · 64 เทสผ่าน

### สลับ engine สกัด PDF เป็น PyMuPDF (แก้ภาษาไทยเพี้ยน) — พิสูจน์กับไฟล์จริงแล้ว
ไทยวางสระ/วรรณยุกต์เหนือพยัญชนะ และเครื่องมือออกแบบ (Canva ฯลฯ) เขียน glyph พวกนี้ลง content
stream **หลัง** พยัญชนะตัวถัดไป → ทั้งการเรียงตามพิกัด x และการอ่านตามลำดับ stream ผิดทั้งคู่

**วัดจริงกับเรซูเม่ไทย 2 ใบ (2026-09-01):**

| engine | ไฟล์ 1 | ไฟล์ 2 (เนื้อไทยเยอะ) |
|---|---|---|
| pdfplumber | `จรี วฒั น์ ศักดิ วงษ์` ❌ | `นกั ศึกษาปส ดุ ท้าย`, `มหาวทิ ยาลัย` ❌ |
| pypdfium2 | 303 บรรทัด หั่นเป็นเศษ ❌ | 301 บรรทัด `ใช้ช`/`ช้`/`ว`/`่` ❌ **แย่กว่าเดิม** |
| **PyMuPDF** | `จีรวัฒน์`, `จ.ร้อยเอ็ด` ✅ | `รับผิดชอบตรงต่อเวลา`, `ปริญญาตรี คณะการบัญชี...` ✅ |

**บทเรียน:** สมมติฐานเดิมที่ว่า "อ่านตามลำดับ content stream แล้วไทยจะถูก" **ผิด** — เคย commit
pypdfium2 ไปแล้วรอบหนึ่งก่อนได้ไฟล์จริงมาทดสอบ แล้วต้องถอยกลับ อย่าเปลี่ยน engine กลับไปหาตัวที่
license ดีกว่าโดยไม่รันเทียบกับไฟล์ไทยจริงซ้ำ
- [pdf_extractor.py](../backend/app/utils/pdf_extractor.py): `_extract_pymupdf` เป็นหลัก →
  fallback `_extract_pdfplumber` เมื่อ error **หรือคืนว่าง**
- ⚠️ **PyMuPDF = AGPL-3.0** (ผู้ใช้รับทราบและเลือกเอง) ถ้าเปิดให้คนนอกใช้ผ่านเน็ตต้องเปิดซอร์สทั้งระบบ
- ล้าง `\r` ด้วย ไม่ใช่แค่ `\x00` · `MAX_PDF_PAGES` (default 30) ปิดงานค้าง decompression bomb
  ใน [04_security.md](04_security.md)
- เทสต์ `test_pdf_extractor.py` 7 เคส (รวม 71) — **แต่ไม่มีเคสไหนครอบบั๊กไทยจริง**: PDF ที่ reportlab
  สร้าง (+ฟอนต์ TLWG) บั๊กไม่เกิด เพราะวางข้อความทั้งบรรทัดเป็นก้อนเดียว พิสูจน์ได้ด้วยไฟล์จริงเท่านั้น
- ⚠️ ข้อจำกัดที่เหลือ: บางไฟล์ฝังฟอนต์ที่ ToUnicode เสีย วรรณยุกต์ออกมาเป็นละติน (`เปqน`, `แก้ปaญหา`)
  เป็นความเสียของไฟล์ ไม่ใช่ของ engine — แก้ได้ด้วยตารางแมปเฉพาะฟอนต์ ยังไม่ทำ
- ⚠️ **ไม่แก้ย้อนหลัง** — แถวเดิมเก็บ `raw_resume_text` ที่เพี้ยนไปแล้ว และ `reprocess` ใช้ข้อความเดิมซ้ำ
  ผู้สมัครที่ชื่อเพี้ยนต้อง **อัปโหลดไฟล์ใหม่**

### กันอัปโหลดไฟล์เดิมซ้ำ (dedupe ด้วย sha256 ต่อหนึ่งตำแหน่งงาน)
เดิม `upload_resumes` ไม่ดูเลยว่าเคยเห็นไฟล์นี้หรือยัง → PDF ใบเดิมอัปสองครั้ง = ผู้สมัคร 2 แถว,
กราฟรัน 2 รอบ (~3 chat calls ทิ้งฟรีต่อใบ จากโควตา 20/วัน) และเปิดช่องส่งอีเมลหาคนเดิมสองครั้ง
- คอลัมน์ `candidates.resume_sha256` + `UNIQUE (job_id, resume_sha256)` (idempotent DDL)
- ตัดสินด้วย **hash ของไบต์** ไม่ใช่ชื่อไฟล์ (เปลี่ยนชื่อแล้วอัปใหม่ต้องยังโดนจับ — ทดสอบแล้ว)
  และไม่ใช่อีเมลที่ LLM แกะ (ตอนอัปโหลดยังไม่มี + มาจาก PDF ที่ใครก็อัปได้)
- เช็ค **ก่อน** แกะข้อความ (ไม่เสียเวลาแกะซ้ำ) + `ON CONFLICT DO NOTHING` กันสองคนอัปพร้อมกัน
  — ห้ามเปลี่ยนเป็น catch `UniqueViolation` เพราะ statement ที่ error จะทำให้ทรานแซกชันทั้ง batch abort
- ตรรกะตัดสินแยกเป็นฟังก์ชันบริสุทธิ์ `_is_duplicate_upload` (แพตเทิร์นเดียวกับ `_deletion_blocker`)
  → ยูนิตเทสต์ได้โดยไม่ต้องต่อ DB · `tests/test_upload_dedupe.py` 5 เคส (รวม 76 เทสต์)
- API ตอบ `skipped` / `duplicate_files` (มี default → client เก่าไม่พัง) และหน้าเว็บขึ้นแถบอำพัน
  "ข้ามไฟล์ที่เคยอัปโหลดในตำแหน่งนี้แล้ว N ไฟล์: …"
- ⚠️ แถวที่สร้างก่อนมีคอลัมน์นี้มี `resume_sha256 = NULL` และ backfill ไม่ได้ (ไม่ได้เก็บไบต์ไฟล์ไว้)
  NULL ไม่ชนกันใน Postgres → แถวเก่าจะไม่กันการอัปไฟล์เดิมซ้ำ (เจอจริงในฐาน dev: `6fbb13db`)
- **ทดสอบจริงแล้ว:** อัปครั้งแรก `accepted=1 skipped=0` · อัปซ้ำ `accepted=0 skipped=1` ·
  เปลี่ยนชื่อไฟล์แล้วอัป `accepted=0 skipped=1` · ไม่มีแถวใหม่ ไม่มีกราฟรันเพิ่ม

### ปิดงาน PDF ไทย: ยืนยันถึงระดับ pipeline แล้ว
อัปโหลดเรซูเม่ไทยจริงผ่าน API เข้ากราฟเต็ม → `candidates.full_name` = **`จีรวัฒน์ ศักดิ์วงษ์`**
(ก่อนแก้คือ `จรี วัฒน์ ศักดิวงษ์`) ไม่ใช่แค่ชั้นสกัดข้อความแล้ว

### ด่านกันไฟล์ที่อ่านข้อความไม่ออก (เรซูเม่สแกน/ถ่ายรูป)
เดิม `upload_resumes` เขียน `raw = ""` ลง DB ตรง ๆ แล้วยิงเข้ากราฟต่อ → เสียโควตา ~3 chat calls
ให้ AI วิเคราะห์ความว่างเปล่า ได้ผู้สมัครทักษะว่างคะแนนมั่วปนในรายชื่อ และ API ตอบ `accepted=1`
เหมือนสำเร็จปกติ HR จึงไม่รู้ตัว
- `MIN_RESUME_TEXT_CHARS` (env, default 80) นับเฉพาะอักขระที่ไม่ใช่ช่องว่าง — เทียบของจริง:
  sample อังกฤษสั้นสุด ~350 ตัวอักษร เรซูเม่ไทยจริง 1,951 / 2,870 เกณฑ์จึงกว้างพอที่ของดีผ่านหมด
- `_is_unreadable_resume` เป็นฟังก์ชันบริสุทธิ์ (แพตเทิร์นเดียวกับ `_is_duplicate_upload`)
  และ **`reprocess` เรียกตัวเดียวกัน** — เดิมเช็คแค่ `.strip()` ว่าง จะเกิดเคส "อัปโหลดไม่ผ่าน
  แต่ reprocess ปล่อยผ่าน"
- API ตอบ `unreadable_files` แยกจาก `duplicate_files` (`skipped` = ผลรวมทั้งสอง) หน้าเว็บขึ้นแถบ
  โทน error พร้อมทางแก้ว่าไฟล์อาจเป็นรูปสแกน ให้บันทึกเป็น PDF ที่มีข้อความแล้วอัปใหม่
- `tests/test_upload_dedupe.py` เพิ่มคลาส `TestIsUnreadableResume` (รวม 84 เทสต์)
- **ทดสอบจริงแล้ว:** อัป PDF หน้าเปล่า → `accepted=0 skipped=1 unreadable=['scanned_resume.pdf']`
  จำนวนผู้สมัครเท่าเดิม และ log ยืนยันว่า **ไม่มี LLM call ถูกยิงเลย**
- ⚠️ ขอบเขต: ตรวจได้แค่ "มีข้อความพอไหม" ไม่ได้ตรวจว่า "เป็นเรซูเม่จริงไหม" ไฟล์สแกนที่มีกล่อง
  ข้อความปนมาเกินเกณฑ์จะยังหลุดผ่าน ต้องใช้ OCR ถึงจะครอบได้ (คนละขนาดงาน ยังไม่คุ้ม)

### เก็บกวาดข้อมูล dev ยุคแรก (2026-09-02)
`backend/scripts/cleanup_dev_data.py` — dry-run เป็นค่าเริ่มต้น ต้องใส่ `--apply` ถึงจะลบ
(แพตเทิร์นเดียวกับ `recompute_scores.py`) ไม่เรียก LLM จึงไม่กินโควตา

- **สำรอง DB ก่อนเสมอ** — `pg_dump -F c` ผ่าน container `db` แล้ว `docker compose cp` ออกมาไว้
  **นอก repo** (ไฟล์มี PII ผู้สมัครจริง) กู้คืนด้วย
  `docker compose exec -T db pg_restore -U talentmatch -d talentmatch --clean < backup.dump`
- สคริปต์ **ใช้ `jobs.py::_deletion_blocker` ตัวเดียวกับ API** ไม่เขียนกฎซ้ำ — job ที่เคยส่งอีเมล
  หรือมีพนักงานจะถูกข้าม ไม่ใช่ลบผ่าน
- ⚠️ `active_candidates()` เป็น set ในหน่วยความจำของโปรเซส backend — สคริปต์เป็นคนละโปรเซส
  จึงมองไม่เห็น ต้องมั่นใจเองว่าไม่มีการอัปโหลด/reprocess ค้างอยู่ตอนรัน `--apply`
- ลบ checkpoint ผ่าน `PostgresSaver.delete_thread` เท่านั้น (ห้าม `DELETE` ตรงในตาราง) และเรียก
  **หลัง** commit เหมือน `jobs.py::delete_job` · orphan query ต้อง UNION ทั้ง `checkpoints` +
  `checkpoint_blobs` + `checkpoint_writes` (`checkpoint_migrations` ไม่มี `thread_id`) —
  thread `566187c1…` ที่จดไว้ว่า "5 แถว" จริง ๆ มี **32 แถว** เพราะเดิมนับแค่ตารางเดียว
- **ผลที่รันจริง:** ลบ 2 job (`Senior Python Developer` `3d43035d…`, `Python Developer` `6bafcaff…`)
  → ผู้สมัคร 5 คน + evaluation 4 แถว + checkpoint 5 thread หายตาม cascade, orphan 1 thread หมด
- **หลังเก็บกวาด DB สอดคล้องกันหมด:** jobs 6 (NULL criteria = 0) · candidates 19 = evaluations 19
  = resume_embeddings 19 = checkpoint threads 19 · orphan 0 · 84 เทสผ่านเท่าเดิม
- ⚠️ `Senior Python Developer` ตัวซ้ำที่ `parsed_criteria` **ไม่** NULL (`29270baa…`) เป็นตัวดี ไม่ได้แตะ

### หน้ารายละเอียดผู้สมัคร: ค้นหาคล้ายกันแบบสั่งเอง + บันทึกคำตัดสิน HR (2026-09-02)
- **ปุ่มค้นหาคล้ายกันแบบ ad-hoc** — ยิง `GET /api/v1/candidates/search` (endpoint เดิม) ผ่าน
  `searchCandidates()` ใน `lib/api.ts` **แยก section จาก `similar_candidates` เด็ดขาด** เพราะคนละที่มา:
  อันเดิมมาจาก `retrieve_similar` node ตอนรันกราฟและ persist ไว้ อันใหม่ค้นสด ไม่บันทึก
  - เติมคำค้นเริ่มต้นจาก `job.title` + `parsed_resume.skills` แต่ **ต้องรอทั้ง `c` และ `job`** ก่อน seed
    (SWR สอง request แข่งกัน — ถ้า seed ตอน `c` มาคนเดียวจะได้แต่ทักษะ ไม่มีชื่อตำแหน่ง) และ seed
    **ครั้งเดียว** เพราะหน้านี้ poll ทุก 4 วิ จะเขียนทับสิ่งที่ HR กำลังพิมพ์
  - ต้องกรองตัวเองออกเอง — endpoint สาธารณะไม่ได้ส่ง `exclude_candidate_id` ต่างจาก retriever node
  - ⚠️ `vectors.search` dedupe ตาม *เนื้อหาเรซูเม่* คนเดียวกันที่อัปเข้าหลายตำแหน่งจึงอาจโผล่ในผล
    ด้วย candidate id ของงานอื่น (การกรอง id ตัวเองไม่ครอบเคสนี้ และไม่ควรกรองด้วยชื่อ)
  - หมายเหตุ: หน้า `/search` (ค้นหาผู้สมัครทั่วไป) เรียก endpoint เดียวกันอยู่ก่อนแล้ว
- **บันทึก/เวลาคำตัดสินของ HR** — `get_candidate` เพิ่ม `hd.notes` / `hd.updated_at` เป็น
  `hr_notes` / `hr_decided_at` (JOIN เดิม ไม่ได้เพิ่ม query) แล้วโชว์ในการ์ดสรุปคำตัดสิน
  - ⚠️ **ไม่ใช่ timeline** — `hr_decisions.candidate_id` เป็น UNIQUE + `ON CONFLICT DO UPDATE`
    DB เก็บได้แค่คำตัดสินล่าสุด ถ้าอยากได้ประวัติจริงต้องเพิ่มตาราง append-only แยก
  - กด "แก้ไข" ต้องเติม `hr_notes` เดิมกลับเข้า textarea เพราะ upsert ทับ `notes` ด้วยค่าที่ส่งมา
    เสมอ — ส่งค่าว่าง = ลบเหตุผลเดิมทิ้ง
- ⚠️ ข้อจำกัดตอนทดสอบ: browser pane จับภาพได้เฉพาะ viewport แรกของหน้านี้ ส่วนที่ต้องเลื่อนลง
  ออกมาเป็นภาพดำ (DOM ปกติ) — ตรวจด้วย `read_page`/JS แล้วซ่อน section อื่นชั่วคราวเพื่อถ่ายภาพ

### เฟส 1: หลักฐานทักษะ + อธิบายคะแนน + ความมั่นใจ (2026-09-02)

**1. Evidence — `agents/evidence.py` + `matching_owned` ใน skills.py**
- ⚠️ **บทเรียนใหญ่: ห้ามยัด `skill_evidence` เข้า prompt เดิมของ `resume_parser`**
  ลองแล้ว วัด A/B กับเรซูเม่ไทยจริง (1,951 ตัวอักษร) prompt เก่านิ่ง 2 รอบ แต่ prompt รวม
  ทำให้ **ฟิลด์เดิมแย่ลงแบบวัดได้**: ชื่อ `จีรวัฒน์ ศักดิ์วงษ์` → `Jeerawat Sakwong`,
  วุฒิ `ปริญญาตรี สาขาคอมพิวเตอร์ธุรกิจ มหาวิทยาลัยมหาสารคาม` → `สาขาคอมพิวเตอร์ธุรกิจ`,
  ทักษะ 21 → 26, ปีประสบการณ์ 0.5 → 0.0 · คำว่า "ปริญญาตรี" **ไม่มีในไฟล์** แปลว่า prompt เก่า
  *อนุมาน*ระดับวุฒิถูก แล้วเสียความสามารถนั้นไป · แยกเป็น call ที่สองแล้วกลับมาตรง baseline ทุกตัว
  → **ต้นทุนจริง 4 chat call/คน (เดิม 3)** = free tier รับได้ ~5 คน/วัน
- `verify_evidence` เทียบแบบ **anchor แล้วเทียบหน้าต่างเดียว**: ก้อนยาวสุดก้อนเดียวเข้มไป
  (พิมพ์ผิดกลางประโยคทำให้ของจริงตก) รวมทุกก้อนทั่วไฟล์หลวมไป (ข้อความแต่งขึ้นเก็บตัวอักษร
  กระจายมาจนผ่าน) · **ต้องใส่ `autojunk=False`** ไม่งั้น difflib มองข้อความยาวเกิน 200 ตัวเป็น junk
- ⚠️ ขอบเขต: ตอบว่า "คัดลอกมาจากไฟล์จริงไหม" ไม่ได้ตอบว่า "พิสูจน์ทักษะนั้นจริงไหม"
  และเกณฑ์ 0.8 ยอมให้คำ/ตัวเลขเดียวเพี้ยนได้ (แลกกับการทนฟอนต์ PDF พัง) — มีเทสตรึงไว้
- `matching_owned()` ใหม่ใน skills.py แล้ว **นิยาม `matches()` ทับด้วยตัวมัน** — ตรรกะเทียบทักษะ
  ยังอยู่ชุดเดียว คะแนนไม่ขยับ · จำเป็นเพราะ `gaps` ใช้การสะกดแบบ JD แต่หลักฐานผูกกับการสะกด
  ในเรซูเม่ (JD ขอ `SQL` ผู้สมัครเขียน `PostgreSQL` ผ่านด้วย IMPLIES)
- ⚠️ คุณภาพ quote ขึ้นกับแบบของเรซูเม่: ฉบับที่เป็น "รายการทักษะ" ล้วน จะได้บรรทัดรายการนั้น
  ซ้ำกันหลายทักษะ (ถูกต้องแต่ไม่ค่อยช่วย HR) — LLM ปฏิเสธที่จะแต่งประโยคใช้งานจริงขึ้นมา ซึ่งถูกแล้ว

**2. `explain_score` (`agents/explain.py`)** — template ล้วน ไม่เรียก LLM เพราะ matched/missing
คำนวณเสร็จแล้วใน matcher · เคสสำคัญ: JD ไม่มีเกณฑ์ทักษะเลย matcher บังคับคะแนน = `REVIEW_FROM`
ซึ่งไม่ได้มาจากการเทียบทักษะ ประโยคจึงห้ามพูดว่า "ได้ 50% เพราะ..."

**3. `confidence_level` (ใน `bands.py` ที่เดียวกับ 50/70)** — จากความยาวข้อความ + สัดส่วนหลักฐาน
ที่ยืนยันได้ · `matched_count == 0` = "ไม่มีสัญญาณด้านหลักฐาน" ไม่ใช่ "0%" (ไม่งั้นคนที่ไม่ตรงเกณฑ์
สักข้อจะโดนลดความมั่นใจทั้งที่อ่านเรซูเม่เขาได้ครบ) · ชิปเตือนใช้คู่ `tertiary-fixed`

**4. แก้บั๊กสูตรคะแนน (2026-09-03): JD ที่ระบุเกณฑ์แค่ฝั่งเดียว**
เจอตอนทดสอบ `low` ผ่าน Gemini จริง — AI Engineer มี required 19 ข้อ **preferred 0 ข้อ**
ผู้สมัครตรง 0/19 **แต่ได้ 40%** เพราะฝั่งที่ JD ไม่ระบุถูกนับเป็นผ่านเต็ม (ratio 1.0)
- ⚠️ **บทเรียน: ครั้งแรกผมแก้ผิดจุด** — ไปต่อประโยคอธิบายว่า "คะแนนส่วนนั้นถูกนับให้เต็ม"
  ซึ่งคือการเอาคำอธิบายไปกลบบั๊กของสูตร ตัวเลข 40% ยังผิดอยู่ดีและ HR ก็ยังงง
  (ผู้ใช้ทักว่า "ทำไมได้ 40% HR จะงงมั้ย" ถึงได้กลับมาแก้ที่สูตร แล้วถอนประโยคนั้นออก)
- ทางแก้: **เฉลี่ยน้ำหนักใหม่ตามฝั่งที่ JD ระบุจริง** — น้ำหนัก 60/40 คือความสำคัญ
  *เชิงเปรียบเทียบ* ซึ่งมีความหมายก็ต่อเมื่อมีทั้งสองฝั่ง จึงใช้เป็นตัวหารด้วย
  มีแต่ required → 100×req · มีแต่ preferred → 100×pref · ไม่มีทั้งคู่ → REVIEW_FROM (เหมือนเดิม)
- ผลกระทบ: 3 จาก 21 คน (46→11, 40→0, 40→0) **ทุกคนอยู่แบนด์ "ไม่ผ่าน" เหมือนเดิม**
  ไม่มีเส้นทางกราฟ/คำตัดสิน/อีเมลที่ส่งไปแล้วเปลี่ยน · เจอ 1 ใน 6 ตำแหน่ง (~17%) ไม่ใช่เคสหายาก
- ⚠️ **`scripts/recompute_scores.py` เคยคัดลอกสูตรไปเขียนเอง** (รวม `else 1.0` ที่เป็นบั๊ก)
  ถ้ารันตอนนั้นจะเอาบั๊กกลับมาทับคะแนนที่ถูกต้อง — แยกเป็น `matcher.compute_fit_score()`
  แหล่งความจริงเดียวแล้ว **ห้ามคำนวณคะแนนที่อื่นอีก** (บทเรียนเดียวกับเลข 50/70 ที่เคยกระจาย 6 ที่)
- เพิ่ม `tests/test_scoring.py` — เดิมสูตรคะแนน**ไม่เคยมีเทสตรง ๆ เลย** ทั้งที่เป็นตัวเลขที่ HR ใช้ตัดสินคน
- ⏳ **แถวเก่า 3 แถวใน DB ยังเป็นคะแนนสูตรเดิม** (46/40/40) — รอผู้ใช้ตัดสินใจว่าจะรัน
  `docker compose exec backend python scripts/recompute_scores.py --apply` หรือไม่ (ไม่กินโควตา LLM)

**สถานะการทดสอบ:** 154 เทสผ่าน · e2e จริงผ่าน Gemini ครบทั้ง evidence + explanation +
`confidence=high` (เรซูเม่ไทย 1,951 ตัวอักษร หลักฐาน 3/3) และ **`confidence=low`**
(weak_anan 257 ตัวอักษร → low ถูกต้อง) ตรวจบนเบราว์เซอร์จริงทั้งสองเคส ไม่มี error ใน console
· ⚠️ **`confidence=medium` ยังทดสอบผ่าน LLM จริงไม่ได้** เพราะต้องใช้เรซูเม่ยาว 400–1,199
ตัวอักษร ซึ่งไม่มีในไฟล์ที่มีอยู่ (sample_data = 257/297/341 · เรซูเม่จริง = 1,924–2,870)
— ครอบด้วย unit test 15 เคสรอบ threshold แทน

### คิวงานประมวลผลที่ทนทาน + คุมโควตา Gemini (เฟส 3 งานที่ 1/3, 2026-09-10)

**ปัญหาเดิม 3 ข้อ:** (1) `BackgroundTasks` อยู่ในโปรเซส รีสตาร์ต/hot-reload = งานหายถาวร
กู้ได้ทางเดียวคือ HR เห็นป้าย stalled แล้วกดเอง (2) backoff ใน `llm.py` แก้ได้แค่ RPM
ไม่ช่วยเรื่อง RPD (20 call/วัน/โมเดล) (3) อัปโหลด batch ใหญ่ = ยิงเข้ากราฟทั้งหมดทันที
คนท้าย ๆ ชน RPD แล้วตายเงียบยกแผง

**ที่ทำ** — ไม่เพิ่ม dependency ใหม่เลย (ไม่ Redis/Celery: Postgres มีอยู่แล้ว และ
`FOR UPDATE SKIP LOCKED` ให้การหยิบงานแบบอะตอมมิกครบ):
- ตาราง `processing_queue` (kind/payload/status/attempts) + `llm_quota_usage` (วัน×โมเดล)
- `app/job_queue.py` — กฎบริสุทธิ์ (`estimate_cost`/`classify_failure`/`next_state`) แยกจาก SQL
- `app/queue_worker.py` — daemon thread **ตัวเดียว** ใน lifespan เรียก `runner` ตัวเดิม
- `app/llm_quota.py` — hook นับที่ `structured_invoke_once` จุดเดียว (best-effort)
- ทุกจุดที่เคย `add_task` เปลี่ยนเป็น enqueue: upload / reprocess / decision / bulk
- `queue_status` บน `CandidateSummary`/`Detail` + ชิปบนการ์ด (`_is_stalled` ต้องไม่ตี
  คนที่อยู่ในคิวเป็น "ค้าง")

**พิสูจน์กับ Gemini จริงครบทุกข้อ (2026-09-10):**
- อัปโหลด 3 ไฟล์ → แถวคิว 3 แถวเกิดทันที → worker รัน **ทีละคน** (`running` = 1 เสมอ)
  → `done` ครบ 3 พร้อม evaluation ครบ
- **HITL invariant ยังอยู่:** approve คนที่กราฟจบไปแล้ว (เส้นทาง rewind) → ตัวนับโควตา
  14 → 16 **พอดี +2** (planner + drafter) และ `evaluations.created_at` **ไม่เปลี่ยน**
  (rerun จากต้นจะ DELETE+INSERT แถวนั้นและกิน 4-5 call)
- **โควตาไม่พอ → `deferred_quota` ไม่ใช่ `failed`** และ `attempts` ยังเป็น 0
- **กู้หลังรีสตาร์ต:** ตั้งแถวเป็น `running` แล้ว restart backend → log ขึ้น "กู้งานที่ค้าง
  จากรอบก่อน 1 ชิ้นกลับเข้าคิว" → worker หยิบต่อเองทันที **โดยไม่ต้องกดอะไร**
- **หลังรีสตาร์ต `_active` ว่าง** แต่ `stalled=False` — พิสูจน์ว่า `queue_status` คือตัวที่
  กันป้ายผิดจริง ไม่ใช่ทะเบียนในโปรเซส
- `deferred_quota` ถูกหยิบกลับมาเองเมื่อครบเวลา (ย้อน `updated_at` 20 นาที) โดยไม่ต้องมี cron
- ลบงานทดสอบ → แถวคิว cascade หายครบ (0 แถว)

**ตัวเลขที่ต้องแก้ในเอกสารเก่า:** ต้นทุนต่อผู้สมัคร **ไม่ใช่ 3 call แต่เป็น 4-5**
(`resume_parser` ยิง 2 ครั้งตั้งแต่เฟส 1 คือโปรไฟล์ + หาหลักฐานทักษะ) วัดได้จากรันจริง:
JD 1 ใบ + ผู้สมัคร 3 คน = 14 call พอดี → `COST_BY_KIND["process"] = 5`

**เทส:** 242 ผ่าน (เดิม 204 · ใหม่ `test_queue.py` 21 เคส, `test_queue_worker.py` 10 เคส,
`test_stalled.py` +6, `test_bulk_decision.py` ปรับให้ดักการเข้าคิวแทนการเดินกราฟ +1)

### แก้จุดตัดวันของตัวนับโควตา (ตามหลังงานคิว, 2026-09-10)

**บทเรียน — ตัดสินใจบนสมมติฐานที่ไม่ได้ตรวจ:** ตอนวางแผนงานคิว ผม (Claude) เสนอให้ตัดวัน
ตาม UTC โดยอ้างว่า "`python:slim` ไม่มี tzdata ต้องลง package เพิ่ม" **ซึ่งเป็นการเดา
ไม่ได้เช็คเลย** ความจริงคือ `python:3.12-slim` มี `/usr/share/zoneinfo` ติดมาอยู่แล้ว
เหตุผลเดียวที่ผู้ใช้เลือก UTC จึงไม่มีอยู่จริง — คำถามที่ยกให้ผู้ใช้ตัดสินใจต้องตรวจ
ข้อเท็จจริงที่ใช้ประกอบก่อนเสมอ ไม่งั้นเท่ากับให้เขาเลือกจากข้อมูลผิด

**ความเสียหายที่วัดได้** (สแกนทั้งปี 2026 เทียบกับวันที่ Pacific จริง):

| สูตร | ตอบวันที่ผิด | คิดเป็น |
| --- | --- | --- |
| UTC (ของเดิม) | 2,682 ชม./ปี | 30.6% |
| ลบ 8 ชม. คงที่ | 238 ชม./ปี | 2.7% |
| Pacific จริง | 0 | 0% |

ที่แย่กว่าตัวเลขคือช่องว่างนั้นคร่อมเวลาทำงานพอดี: ตัวนับเราตัดวันตอน 07:00 น. ส่วน Google
รีเซ็ตตอน 14:00 น. (หน้าร้อน) / 15:00 น. (หน้าหนาว) → call ที่ใช้ตอนเช้าโดนคิดสองต่อ
พอบ่ายโควตาจริงรีเซ็ตเป็น 0/20 แต่ตัวนับยังจำยอดเช้าไว้ **ทั้งบ่ายจึงพักงานทิ้งไว้ทั้งที่
ยิงได้** เสียกำลังการผลิตได้ถึง ~4 คน/วัน และ HR เห็นป้าย "เลื่อนไปวันถัดไป" ที่อธิบายไม่ได้

**ที่แก้:** `llm_quota.today()` ใช้ `ZoneInfo(GEMINI_QUOTA_TZ)` (ดีฟอลต์ Pacific) โดยแยก
`quota_date(now, tz)` เป็นฟังก์ชันบริสุทธิ์ตามแพตเทิร์น `rate_limit.hit_and_check`
ไม่แตะ schema ไม่ต้อง migrate (แถวเดิมให้วันที่เดียวกันทั้งสองสูตร ตรวจแล้ว)

**รายละเอียดที่ตรวจจริงในคอนเทนเนอร์ ไม่ใช่เดา:**
- ชื่อโซนที่ไม่มีจริงโยน `ZoneInfoNotFoundError` แต่ชื่อ**ผิดรูป** (ว่าง / มี `../`) โยน
  **`ValueError`** คนละคลาสกัน → ต้อง `except Exception` ไม่งั้น env พิมพ์ผิดทำทั้งแอปล่ม
- `ZoneInfo()` แคชอ็อบเจกต์ในตัว 100k ครั้ง = 0.011 วิ → `lru_cache` มีไว้ให้ log ครั้งเดียว
  ไม่ใช่เพื่อความเร็ว
- แปลง UTC→local ไม่มีความกำกวมแม้วันถอยเวลา 25 ชม. (ความกำกวมเกิดตอนแปลงย้อนทาง)
- สแกน 2 ปี: วันที่ไม่เคยเดินถอยหลัง ไม่มีวันหาย ไม่มีวันซ้ำ
- สแกน 2 ปี: ทางถอย "ลบ 8" ไม่เคยตอบเร็วกว่า Pacific สักครั้ง (ถ้าแก้เป็น 7 พัง 254 ช่วง —
  มีเทส invariant ล็อกไว้ และทดสอบแล้วว่าเทสจับได้จริง)

⚠️ **สมมติฐานที่ยังไม่ได้วัด:** ว่า Google รีเซ็ตตอนเที่ยงคืน Pacific เป็นสิ่งที่ Google ระบุไว้
แต่โปรเจกต์นี้ยังไม่เคยเฝ้าดูจังหวะที่ 429 หายไปจริง ถ้าสังเกตได้เมื่อไรว่ามันรีเซ็ตตาม UTC
ตั้ง `GEMINI_QUOTA_TZ=UTC` แล้วกลับพฤติกรรมเดิมได้ทันทีโดยไม่ต้องแก้โค้ด

**เทส:** 259 ผ่าน (`test_llm_quota.py` 17 เคสใหม่)

### ปากทางรับใบสมัครทางอีเมล — ฝั่ง backend (เฟส 3 งานที่ 2/3, 2026-09-10)

worker ดึงเมลจาก IMAP → จับคู่ตำแหน่งงาน → สร้างผู้สมัคร → เข้า `processing_queue` เดิม
กำแพงข้อ 1 ที่เคยบันทึกไว้ (โควตา 20 call/วัน) ไม่ต้องเขียน throttle ใหม่เลย เพราะคิวจาก
งานที่ 1/3 คุมให้อยู่แล้วทั้ง `deferred_quota` และการรันทีละชิ้น

**ไฟล์ใหม่:** `app/email_intake.py` (worker + จับคู่งาน) · `app/settings.py` (key-value ใน DB
พร้อมแคช 10 วิ) · `app/routers/settings.py` (GET/PATCH สวิตช์) · `app/resume_ingest.py`
(ด่านรับไฟล์ที่แยกออกมาจาก `upload_resumes` ให้สองทางเข้าใช้กฎชุดเดียวกัน)
**ตารางใหม่:** `app_settings`, `email_intake_log`
**ไม่เพิ่ม dependency เลย** — `imaplib` + `email` เป็น stdlib และมีในอิมเมจอยู่แล้ว

**พิสูจน์แล้วในคอนเทนเนอร์:**
- env ไม่ครบ → ปิดถาวร ไม่สตาร์ตเธรดเลย (`_thread is None`) + log บอกสาเหตุตอนบูต
- env ครบแต่สวิตช์ปิด → เฝ้า 45 วิ **ไม่มีความพยายามต่อ IMAP แม้แต่ครั้งเดียว** = หลับสนิทจริง
- กดเปิดเวลา 15:52:40 → worker พยายามต่อ IMAP เวลา 15:52:50 = **10 วินาที ไม่ต้องรีสตาร์ต**
- ต่อไม่ได้ (ตั้งโฮสต์ปลอม) → บันทึกเป็น `last_error` ให้ HR เห็นผ่าน API worker ไม่ตาย
- ปิดกลับ → เงียบสนิทอีกครั้ง (0 ครั้งใน 35 วิ)
- **โควตา LLM ไม่ขยับเลยตลอดการทดสอบ** (18 เท่าเดิม) ยืนยันว่า intake ไม่แตะ LLM ทางใดเลย

**กับดัก IMAP 3 ข้อที่ต้องรู้ (เจอตอนออกแบบ ไม่ใช่ตอนพัง):**
1. **UID ไร้ความหมายถ้าไม่มี UIDVALIDITY** — กล่องถูกสร้างใหม่แล้วเลข UID เป็นคนละชุด
   ถ้าใช้ `last_uid_seen` เดิมต่อจะข้ามเมลใหม่ทั้งกล่องเงียบ ๆ หรือดูดซ้ำทั้งกล่อง
   จึงเก็บคู่กันและรีเซ็ตเมื่อค่าเปลี่ยน
2. **`UID n:*` คืนฉบับล่าสุดมาเสมอแม้ไม่มีของใหม่** — ต้องกรอง `uid >= start` ในโค้ดอีกชั้น
   ไม่งั้นจะประมวลผลฉบับเดิมทุกรอบ poll แล้วเสียโควตาไปเรื่อย ๆ
3. **ต้องใช้ `BODY.PEEK[]` ไม่ใช่ `BODY[]`** — ตัวหลังตั้งแฟล็ก `\Seen` ให้อัตโนมัติ =
   ไปแตะสถานะเมลในกล่องที่ HR ยังอ่านเองอยู่ (คู่กับ `select(readonly=True)`)

**`last_uid_seen` เดินทีละฉบับ ไม่ใช่ท้าย batch** — worker ตายกลางทางแล้วรอบหน้าต้องไม่
เริ่มจากศูนย์ (มีเทสจับ: ให้ฉบับกลางโยน exception แล้วเช็คว่าฉบับที่เหลือยังไปต่อและ uid เดินถูก)

**หมายเหตุเก่าที่ล้าสมัยและแก้แล้ว:** กำแพงข้อ 3 เดิมเขียนว่า "dedupe ด้วยอีเมลผู้ส่ง
(upload เดิมไม่กันซ้ำ)" — ตอนนี้ upload กันซ้ำด้วย `UNIQUE (job_id, resume_sha256)` แล้ว
จึง **ไม่ทำ dedupe ด้วยผู้ส่ง** เพราะจะบล็อกเคสที่คนเดิมส่งเรซูเม่ฉบับแก้มาใหม่ และ
header `From` ปลอมได้อยู่ดี (ผู้ใช้ยืนยันทางเลือกนี้)

⚠️ **ยังทดสอบกับกล่องเมลจริงไม่ได้** — MailHog รับแค่เมลขาออก ต้องมี Gmail App Password
ของจริง ขั้นตอนทดสอบ manual อยู่ใน [03_environment.md](03_environment.md)

**เทส:** 297 ผ่าน (เดิม 259 · `test_email_intake.py` 24 เคส, `test_settings.py` 14 เคส)

### ปากทางรับใบสมัครทางอีเมล — ฝั่ง frontend + ทดสอบรวม (เฟส 3 งานที่ 3/3, 2026-09-10)

**หน้า settings กับเมนูมีอยู่แล้ว** (การ์ดเลือกธีม + ลิงก์ท้าย side-nav) จึงเพิ่มการ์ดใหม่
ลงหน้าเดิม ไม่สร้างหน้าใหม่และไม่เพิ่มเมนูซ้ำ

**ไฟล์ใหม่:** `components/email-intake-card.tsx` (สวิตช์ + สถานะ + คำเตือน) ·
`components/apply-address.tsx` (ที่อยู่รับสมัครต่อตำแหน่ง + ปุ่มคัดลอก)
**backend เพิ่มนิดเดียว:** `apply_address_template()` คืนรูปแบบที่อยู่จาก `IMAP_USER`

**🔴 บั๊กที่เจอตอนทดสอบรวม (ถ้าไม่ทดสอบทั้งสายจะไม่มีวันเจอ):**
ตัวจับคู่ hardcode ว่าที่อยู่ต้องเป็น `apply+<uuid>@` แต่ `apply_address_template()`
สร้างที่อยู่จาก `IMAP_USER` พอกล่องชื่อ `recruit@` หน้าเว็บก็บอกผู้สมัครว่า
`recruit+<uuid>@` ซึ่งตัวจับคู่ไม่รู้จัก → **ใบสมัครทุกฉบับที่ส่งมาตามที่ระบบบอกเอง
ถูกตีเป็น unmatched แบบเงียบ ๆ** แก้โดยให้ regex รับ local part อะไรก็ได้ก่อน `+`
และเพิ่มเทสล็อกความสัมพันธ์ไว้: **ที่อยู่ที่ `apply_address_template()` สร้าง ต้องถูก
`extract_job_id()` จับได้เสมอ** (พารามิเตอร์ 4 แบบชื่อกล่องต่างกัน)
เทสเดิม 24 เคสผ่านหมดทั้งที่บั๊กนี้อยู่ เพราะทุกเคสใช้ `apply+` เป็นตัวอย่าง —
บทเรียน: เทสที่ยกตัวอย่างชุดเดียวกับที่โค้ดสมมติไว้ ไม่ได้พิสูจน์อะไรเลย

**ผ่อนเทสความปลอดภัยหนึ่งข้อโดยตั้งใจ:** เดิม `test_response_ต้องไม่มีความลับของ_imap`
ห้ามอักขระ `@` โผล่ใน response ทั้งก้อน ซึ่งกว้างเกินไป — ที่อยู่รับสมัครคือสิ่งที่จะถูก
ประกาศให้ผู้สมัครทั้งโลกส่งเมลเข้ามา ไม่ใช่ความลับ · เปลี่ยนเป็นห้ามเฉพาะ `password`,
`imap_host`, พอร์ต และเพิ่มเทสว่าที่อยู่ต้องไม่มีรหัสผ่านปน

**พิสูจน์บนเบราว์เซอร์จริง (localhost:4000):**
- `imap_configured=false` → สวิตช์ `disabled` จริงใน DOM + ข้อความ "ติดต่อผู้ดูแล"
- ตั้ง env แล้ว → สวิตช์กดได้ · กดเปิด → `PATCH` 200 → **รีโหลดทั้งหน้าแล้วยังเปิดอยู่**
  (พิสูจน์ว่า persist ใน DB ไม่ใช่ state ในหน้า)
- ทั้งโหมดมืดและสว่างอ่านออก · console ไม่มี error
- ป้อนอีเมลจริง (แนบ PDF จาก sample_data) เข้า `process_message` → `matched` →
  แถว `candidates` → แถวคิว `queued` ที่ `payload->>'source' = 'email'` →
  **หน้าเว็บของงานนั้นเห็นผู้สมัครโผล่มาพร้อมป้ายสถานะคิวทันที** โดยไม่ต้องแก้ UI เดิมเลย
- ปุ่มคัดลอก: เบราว์เซอร์ทดสอบบล็อก clipboard API → **ทางสำรองทำงาน** (เลือกข้อความให้
  กด Ctrl+C ได้) ซึ่งเป็นเส้นทางที่ทดสอบยากกว่าและได้พิสูจน์ไปแล้ว
- ปิดรับสมัครงานนั้น → กล่องที่อยู่หายไปตามเงื่อนไข (กันไม่ให้ HR ประกาศที่อยู่ของงาน
  ที่ worker จะปฏิเสธอยู่ดี)

⚠️ **ที่ยังพิสูจน์ไม่ได้วันนี้:** โควตา Gemini ใช้ไป 18/20 ส่วนงาน `process` ต้องการ 5
ผู้สมัครที่มาจากอีเมลจึงขึ้น `deferred_quota` ไม่ได้รันกราฟจนจบ — คะแนน/แบนด์/HITL ของ
รายนั้นยังไม่ออก · ส่วนที่พิสูจน์แล้วคือทั้งสายจนถึงด่านโควตา ซึ่งใช้จุดเข้าคิวเดียวกับ
การอัปโหลดมือทุกประการ (พิสูจน์ครบไปแล้วในงานที่ 1/3)

**เทส:** 307 ผ่าน (เดิม 297 · เพิ่มเทสความสัมพันธ์ template↔matcher และเทสที่อยู่รับสมัคร)

### กระดานติดตามผู้สมัครหลังผ่านการคัดกรอง (เฟส 4 งานที่ 1/3 + 2/3, 2026-09-11)

**ปัญหา:** กราฟตัดสินว่า "ควรเชิญไหม" จบแล้วก็จบ แต่หลังจากนั้นไม่มีที่ไหนบอกว่าคนที่
เชิญไปแล้วเดินไปถึงไหน HR ต้องจำเองหรือจดใส่ไฟล์แยก

**ทำอะไร:** ตาราง `hiring_stage` (หนึ่งคนหนึ่งแถว, PK = candidate_id) + `GET
/api/v1/jobs/{id}/board` + `PATCH /api/v1/candidates/{id}/stage` และหน้ากระดาน 6 คอลัมน์
ที่ `/jobs/{id}/board` พร้อมแท็บสลับกับหน้ารายชื่อเดิม

**สิ่งที่ยึดไว้เป็นหลัก:**
- **เลเยอร์นี้อ่านผลของกราฟอย่างเดียว** ไม่ import graph/runner/nodes ไม่เรียก LLM
  สักครั้ง ไม่เคยเขียนอะไรกลับเข้า state ของกราฟ
- **"รับเข้าแล้ว" ไม่ใช่ค่าใน `stage`** — อนุมานจากการมีแถวใน `employees` เท่านั้น
  ถ้าเก็บสองที่จะมีวันที่ขัดกันเองแล้วไม่มีใครรู้ว่าอันไหนจริง
- **เงื่อนไข "ใครขึ้นกระดาน" เรียก `bands.should_auto_advance()`** ผ่าน
  `app/hiring_board.py` (ฟังก์ชันบริสุทธิ์ ไม่ต่อ DB) ไม่มีเลข 70 ในไฟล์ใหม่
  การกรองทำใน Python ไม่ใช่ WHERE — กรองใน SQL คือการสำเนาเส้นแบ่งเพิ่มอีกที่
- **GET ห้าม INSERT** (write-on-read) ไม่งั้น `moved_at` กลายเป็น "เวลาที่ HR เปิดหน้า"
- การ์ดที่เคยขึ้นกระดานแล้ว **ห้ามหายเงียบ** ไม่ว่าคะแนนหรือคำตัดสินจะเปลี่ยนไปอย่างไร
  — เคสที่ขัดกันขึ้นป้ายเตือน (`screening_conflict`) แทนการซ่อนการ์ด
- ย้ายการ์ดได้สองทางเสมอ: ลาก (HTML5 DnD ไม่ลง library ใหม่) และเมนู `<select>` —
  เมนูไม่ใช่ของเสริม เพราะ DnD ล้วน ๆ เข้าถึงด้วยคีย์บอร์ดไม่ได้เลยและบนมือถือแทบใช้ไม่ได้
- ลากเข้า "รับเข้าแล้ว" เปิด `HireEmployeeDialog` ตัวเดิม ไม่ยิง PATCH (backend ตอบ 400)
  · กดยกเลิก = การ์ดอยู่ที่เดิม เพราะยังไม่เคยย้ายมันตั้งแต่แรก

---

### บันทึกผลสัมภาษณ์จริง (เฟส 4 งานที่ 3/3, 2026-09-12)

**ปัญหา:** ระบบร่างคำถามพร้อมแนวคำตอบให้ HR แล้ว แต่พอสัมภาษณ์เสร็จจริงไม่มีที่บันทึกผล
— ข้อมูลชุดเดียวที่บอกได้ว่าคะแนนของ AI แม่นแค่ไหนหายไปกับกระดาษทุกครั้ง

**ทำอะไร:** ตาราง `interview_outcome` (PK = candidate_id, CASCADE) +
`PUT /api/v1/candidates/{id}/interview-outcome` (upsert) + ฟอร์มในหน้า deep dive ที่
seed คำถามมาจาก `evaluations.interview_plan` ให้ HR ให้คะแนนรายข้อ 1–5 + โน้ต แล้วสรุป
ผ่าน/สำรอง/ไม่ผ่าน · ผลโผล่เป็นป้ายบนการ์ดกระดานด้วย

**สิ่งที่ยึดไว้เป็นหลัก:**
- **ห้ามแตะ `hr_decisions` และห้ามเรียกกราฟ** `hr_decision` ตอบ "ให้ผ่านไปสัมภาษณ์ไหม"
  ซึ่ง `route_candidates` อ่านไปเลือกเส้นทาง ส่วน `result` ตอบ "สัมภาษณ์แล้วเป็นยังไง"
  ถ้าปนกัน กราฟจะถูกปลุกให้ตัดสินใหม่โดยไม่มีใครสั่ง แล้วคนที่สัมภาษณ์ไม่ผ่านจะถูกร่าง
  อีเมลปฏิเสธส่งออกเองเงียบ ๆ — มีเทสนับแถวและอ่านค่าของ `hr_decisions` ก่อน/หลังกันไว้
- **บันทึกผลแล้วเลื่อนขั้นให้เอง แต่เลื่อนขึ้นทางเดียว** `_next_stage_after_outcome()`
  เป็นฟังก์ชันบริสุทธิ์: ไม่มีแถว/`invited`/`scheduled` → `interviewed` ·
  `interviewed`/`offer`/`declined` → ไม่แตะ · `offer` ห้ามย้อนเพราะบันทึกย้อนหลังต้องไม่
  ดึงคนที่ยื่นข้อเสนอไปแล้วกลับมา · `declined` อยู่นอกบันได ถ้าลากกลับเท่ากับปลุกการ์ด
  ที่ HR จงใจพักไว้ · การเขียนสองตารางอยู่ในทรานแซกชันเดียวกัน
- **ช่วงคะแนน 1–5 บังคับที่ Pydantic ที่เดียว** — `CHECK` ของ Postgres ตรวจค่าข้างใน
  JSONB array ไม่ได้โดยไม่เขียน expression ที่ไม่มีใครอ่านออก ถ้าด่านนี้หลุดจะไม่มีอะไรกัน
- ฟอร์มจับคู่คะแนนเดิมกลับเข้าคำถาม **ด้วยข้อความคำถาม ไม่ใช่ index** — คนที่ถูก
  reprocess จะได้แผนชุดใหม่ที่ลำดับไม่ตรงเดิม จับคู่ด้วยตำแหน่งจะเอาคะแนนไปแปะผิดข้อ
- ผู้สมัครที่ไม่มี `interview_plan` (เช่นถูกปฏิเสธไปแล้ว) ไม่เห็นปุ่มนี้เลย

**กับดักที่เจอจริงระหว่างทำ:**
- **โมดัลใหม่ถูกแถบเมนูด้านข้างทับหัว** เนื้อหาของทุกหน้าอยู่ในกล่อง `relative z-10` ของ
  `app-shell` ซึ่งเป็น **stacking context** — โมดัลที่เกิดข้างในนั้นถูกเพดาน z=10 กดไว้
  ส่วนแถบเมนูเป็น `fixed z-50` จึงชนะเสมอ ไม่ว่าจะใส่ z เท่าไรข้างใน แก้ด้วย
  `createPortal` ไปที่ `document.body` · **โมดัลเดิมสองตัว
  (`hire-employee-dialog`, `confirm-dialog`) มีบั๊กเดียวกันแต่ยังไม่แสดงอาการ** เพราะ
  กว้างแค่ `max-w-lg` จึงพอดีหลบพ้นแถบเมนูที่จอ 1024px ขึ้นไป — ที่แคบกว่านั้นทับเหมือนกัน
- **`to_jsonb(io)` บน LEFT JOIN ที่ไม่แมตช์คืน object ที่มีแต่ค่า null ไม่ใช่ NULL**
  ถ้าไม่ครอบ `CASE WHEN io.candidate_id IS NOT NULL` Pydantic จะเจอ `result=None` ซึ่ง
  เป็นฟิลด์บังคับ แล้วผู้สมัคร**เกือบทุกคนในระบบ**เปิดหน้ารายละเอียดไม่ได้ (มีเทสกันไว้)
- `candidates.py::get_candidate` splat ทั้ง row เข้าโมเดล (`CandidateDetail(**row)`)
  ชื่อ alias ใน SELECT จึงต้องตรงกับชื่อฟิลด์เป๊ะ ๆ และคีย์ที่ไม่ใช่ฟิลด์ต้อง `pop` ทิ้ง
- `interview_result` ต้องเติมใน **ทั้งสองเควรี**ของ `hiring_board.py` ไม่ใช่แค่
  `get_board` เพราะทั้งคู่ประกาศ `response_model=BoardItem` เดียวกัน · หน้ากระดานตอนนี้
  ทิ้ง response ของ PATCH แล้ว revalidate เอา แต่อันที่คืนไม่ครบคือกับดักรอผู้เรียกรายต่อไป

**พิสูจน์แล้วบนเบราว์เซอร์จริง:** บันทึกผล → การ์ดย้ายไป "สัมภาษณ์แล้ว" เองโดยไม่ต้องลาก
→ ป้ายผลขึ้นถูกสี · กด "แก้ไขผล" ค่าเดิมกลับมาครบทุกช่อง แก้แล้วทับในแถวเดิม (ยังมีแถวเดียว
`created_at` คงที่ `updated_at` ขยับ) · คนที่อยู่ `offer` บันทึกผลแล้วยังอยู่ `offer` ·
คนที่ไม่มีแผนสัมภาษณ์ไม่มีปุ่ม · ลากการ์ดข้ามคอลัมน์แล้วป้ายผลยังอยู่ · **`hr_decisions`
เท่าเดิม (6 แถว ค่าเดิม) และ `llm_quota_usage` เท่าเดิม (19) ตลอดการทดสอบทั้งหมด** ·
คอนทราสต์ชิปทั้งสองธีม 7.2:1 ขึ้นไป · มือถือ 375px ไม่มี horizontal scroll ทั้งหน้า
(`scrollWidth === clientWidth === 375`) โมดัลเลื่อนในตัวเอง · console ไม่มี error

**ข้อจำกัดที่ยังอยู่:** การลากด้วยเมาส์จริงยังต้องให้คนทดสอบเอง — เมาส์สังเคราะห์ผ่าน CDP
ไม่ทริกเกอร์ HTML5 DnD (ข้อจำกัดของเครื่องมือ ไม่ใช่บั๊กของโค้ด) ที่ยืนยันได้คือสายตัวจัดการ
ทั้งเส้นเมื่อยิง `DragEvent` + `DataTransfer` จริงเข้าไป ซึ่งย้ายและ persist สำเร็จ

**เทส:** 376 ผ่าน (เดิม 347 · เพิ่ม 29 เทสของผลสัมภาษณ์)

### กราฟหยุดกลางทางแล้วงานที่จ่ายโควตาไปแล้วหาย + กู้ Jeerawat Sakwong (2026-09-17)

**อาการที่ผู้ใช้เจอ:** Jeerawat Sakwong (`6fbb13db…`, คะแนน 60) ถูก HR อนุมัติเมื่อ 3 ก.ย.
แต่หน้ารายละเอียดไม่มีคำถามสัมภาษณ์และร่างอีเมล ผู้ใช้สงสัยว่าเป็นเพราะฟีเจอร์สร้างทีหลัง —
**ไม่ใช่** ตรวจ checkpoint แล้ว planner สร้างคำถาม 7 ข้อสำเร็จ แต่กราฟล้มก่อน `email_drafter`
(น่าจะโควตาหมด · log วันนั้นหายไปพร้อมคอนเทนเนอร์เก่า ยืนยันไม่ได้ 100%) ค้างที่
`next=('email_drafter',)` สมัยนั้นยังเป็น BackgroundTasks จึงไม่มีอะไรกลับมาทำต่อ

**ต้นเหตุในโค้ด (ทั้งหมดอยู่ใน `agents/runner.py`) และที่แก้:**
1. **คำถามลง DB ตอนกราฟจบเท่านั้น** → `_advance` เดินด้วย `stream(stream_mode="updates")`
   แล้ว `_persist_plan` ทันทีที่ planner เสร็จ (ล้าง `email_draft` เก่าไปด้วย ไม่แตะ
   `email_sent_at`) · แผนว่างของคนถูกปฏิเสธไม่บันทึกกลางทาง
2. **งาน `process` ที่คิวลองใหม่ รันกราฟใหม่จากต้น** — `invoke(ข้อมูลตั้งต้น)` บน thread ที่มี
   checkpoint = LangGraph เริ่มจาก entry จ่าย parser/auditor ซ้ำ และ `_persist_evaluation`
   ลบแถว evaluations ทิ้ง → `_resume_point` (บริสุทธิ์) ตัดสินว่าเริ่มใหม่ / เดินต่อกลาง
   ช่วงคัดกรอง / ข้ามไปช่วงหลัง และไม่ persist evaluation ซ้ำถ้ามีแถวแล้ว
3. **`update_state` ไม่ระบุ `as_node` เดาผิด** — เจอระหว่างเขียนเทส ไม่ได้อยู่ในแผนแรก:
   ถ้า checkpoint ล่าสุดเกิดจาก `update_state` (เช่น ย้อนแล้ว planner ล้ม) การลองใหม่ทำให้
   `next` ว่าง กราฟ "จบ" ทั้งที่ไม่ได้ทำอะไร **คิวนับว่าสำเร็จแบบเงียบ** → ระบุ `as_node` เอง
   ทุกกรณีใน `resume_after_decision`
4. **สถานะรายงานว่า "รอ HR" ทั้งที่ตัดสินแล้ว** → `resolve_graph_status` (บริสุทธิ์) เพิ่ม
   `interrupted` · router ทับเป็น `processing` เมื่อกำลังรัน/รอคิว (`_effective_graph_status`)
   กันปุ่มกะพริบ · เส้นคะแนนเรียก `bands.should_auto_advance`
5. **ไม่มีทางสั่งทำต่อ** → `POST /api/v1/candidates/{id}/resume` (404 → 409 กำลังรัน →
   409 มีคิว → 409 ไม่ได้ค้าง) เข้าคิวด้วย kind เดิม: มีคำตัดสิน = `resume_after_decision`
   ไม่มี = `process` · หน้า deep dive มีแถบเตือน + ปุ่ม "ทำต่อจากจุดที่ค้าง" วาง**นอก**
   เงื่อนไขที่ซ่อนข้อความเมื่อตัดสินแล้ว (ไม่งั้นคนที่ต้องใช้มันที่สุดจะไม่เห็น)

**พิสูจน์พฤติกรรม LangGraph ด้วยกราฟจำลองก่อนลงมือ** (InMemorySaver ไม่เรียก LLM):
stream คืนก้อน planner ก่อน drafter ล้ม · `update_state` ตอนค้างที่ drafter ต่อที่ drafter
ได้ · `invoke(initial)` บนกราฟค้าง = รันจากต้น · ย้อนแล้วล้มแล้ว `update_state` ไม่ระบุ
`as_node` = `next` ว่าง

**เทส:** `tests/test_graph_recovery.py` ใช้ `build_graph()` จริง + InMemorySaver + mock LLM
และให้ parser/auditor/jd_analyzer **โยน AssertionError ถ้าถูกเรียก** เพื่อจับการรันจากต้น ·
เทส endpoint **จับ `enqueue` ไว้ ไม่ insert แถวคิวจริง** เพราะ worker ใน backend กำลังทำงาน
ถ้าหยิบแถวของเทสไปได้จะเรียก Gemini จริง · รวม 415 ผ่าน (เดิม 385)

**กู้ Jeerawat ผ่านปุ่มจริงบนเบราว์เซอร์:** โควตาวันนั้น 0 → **1 พอดี** (drafter อย่างเดียว) ·
คำถาม 7 ข้อใน DB **ข้อความตรงกับใน checkpoint** (ไม่ได้สร้างใหม่) · ร่างอีเมลเป็น invitation ·
สถานะ `completed` · `hr_decisions` และ `evaluations.created_at` เหมือนเดิมทุกค่า · คิว `done`
attempts 0 · แถว `a8ce77b3` ไม่ถูกแตะ ขึ้น `interrupted`

### เทียบทักษะ: เลขเวอร์ชันและวงเล็บ (2026-09-22)

เรซูเม่เขียน "HTML", "CSS", "Visual Studio Code" แต่เกณฑ์ (Junior Web Developer) เขียน "HTML5",
"CSS3", "VS Code", "JavaScript (ES6+)" — `html5` กับ `html` เป็นคนละ token จึงไม่ตรงกัน
แก้ใน [skills.py](../backend/app/agents/skills.py) สองจุด:
- `canonical()` ตัดวงเล็บก่อนเทียบ ("JavaScript (ES6+)" → javascript, "Node.js (Express)" → node js)
  ชื่อที่เก็บ/แสดงยังเป็นต้นฉบับ · ถ้าตัดแล้วว่างใช้ชื่อเดิม
- ALIASES เพิ่มคู่ที่ระบุตรง ๆ: html5→html, css3→css, es6/es6+/es2015/ecmascript→javascript,
  vs code/vscode→visual studio code · **ไม่ตัดเลขทิ้งทุกชื่อ** เพราะเลขเป็นส่วนของชื่อจริงได้
  (S3, EC2, Web3, Raspberry Pi 3 — มีเทสกันไว้)

ผลกับข้อมูลจริง (บันทึกด้วย `criteria_edit.rescore_job` ต่อตำแหน่ง ไม่ใช่ `recompute_scores --apply`
เพราะสคริปต์นั้นอัปเดตแค่ fit_score/gap_analysis ไม่อัปเดตคำอธิบาย/หลักฐาน/ความมั่นใจ และไม่สน
เกณฑ์ที่ถูกตัดเพราะอคติ): เปลี่ยน 4 จาก 30 คน ทั้งหมดใน Junior Web Developer · JEERAWAT SAKWONG
40 → 60 ข้ามแบนด์ ไม่ผ่าน → รอ HR (ขึ้นป้าย "เกณฑ์เปลี่ยน ตรวจอีกครั้ง") · ปรียานท์ 19-20 → 38-40

ต่อด้วยเฟรมเวิร์ก JS ที่เขียนได้หลายแบบ: React/React.js/ReactJS, Vue, Next, Express, Nuxt, NestJS
ตรงกันทุกทิศ (ALIASES ระบุรายชื่อ ไม่ตัด "js" ทุกชื่อ — Chart.js → "chart" จะไปตรง "Org Chart")
· AngularJS = Angular.js แต่ ≠ Angular (เดิม "Angular.js" ตรงกับ "Angular" ผิด) · ไม่มีคะแนนใครเปลี่ยน
· ผลข้างเคียงของ alias es6+→javascript: ตัดฝั่งเกณฑ์ที่ dedupe ด้วย canonical ทำให้ "ES6+" ซ้ำกับ
"JavaScript" — จัดฝั่งใหม่ตำแหน่ง 3243593d ด้วย resort_jd_criteria.py (ปรียานท์ 38 → 40)

### ฟีเจอร์ช่วย HR ตัดสินใจ (2026-09-22 → 09-23)

- **ดูเรซูเม่ต้นฉบับ + ข้อความที่ระบบอ่านได้** — ตาราง `candidate_files` (PDF เก็บตอนรับไฟล์
  เท่านั้น คนที่เข้ามาก่อนหน้าไม่มีไฟล์ตลอดไป) · `GET /candidates/{id}/resume.pdf` เปิดเป็น blob
  ในแท็บใหม่ **ไม่ฝังในหน้าเรา** เพราะไฟล์มาจากคนนอก
- **รูปโปรไฟล์จากเรซูเม่** — `resume_photo.py` เลือกรูปด้วย heuristic ล้วน (ไม่ใช้ LLM/face detection)
  ดึงทุกครั้งที่รับไฟล์ แต่หน้าคัดกรองแสดงเฉพาะเมื่อเปิดสวิตช์ `screening_photos` (ดีฟอลต์ปิด —
  รูปทำให้เกิดอคติ) หน้าพนักงานแสดงเสมอ
- **ฮิสโตแกรมกระจายคะแนน + ปักหมุดคนที่ดูอยู่** และ **ทักษะที่ขาดบ่อยในตำแหน่ง** รวมเป็นการ์ดเดียว
  (เส้นแบ่งแบนด์อ่านจาก `bands.py` ผ่าน API ไม่เขียน 50/70 ที่หน้าเว็บ) · จอแคบแกนเหลือ 0/50/70/100
- **ขั้น "ยืนยันเกณฑ์" ก่อนสร้างตำแหน่ง** — `POST /jobs/analyze` ให้ AI ร่าง HR ตรวจ แล้วค่อย
  `create_job(criteria=...)` · กันปัญหา AI แตกเกณฑ์ไม่เหมือนกันทุกรอบตั้งแต่ต้นทาง
- **ตัวอักษรไทยจาก PDF เป็น ▯** — glyph ในช่วง PUA U+F700–F71A แปลงกลับใน `pdf_extractor.normalize_thai_pua`
  และซ่อมแถวเดิมด้วย `scripts/fix_thai_pua.py`
- **จัดฝั่งเกณฑ์จาก JD** — หัวข้อย่อยไม่นับเป็นทักษะ, Nice-to-Have ไม่ตกไปฝั่งต้องมี
  (`jd_analyzer._preferred_lines`, `_heading_items`) · ซ่อมตำแหน่งเดิมด้วย `scripts/resort_jd_criteria.py`

### UI + ความเร็ว (2026-09-23)

- หน้าเข้าสู่ระบบใหม่ + ปุ่มสลับธีม · spinner ทุกจุดที่ต้องรอ · ชิปสถานะคิวอ่านออกทั้งสองธีม
- หน้ารายละเอียดผู้สมัครเป็นสองชั้น: บนสองคอลัมน์ (ข้อมูล | เรดาร์+ที่มาของคะแนน) ล่างเต็มความกว้าง
  (ผลตรวจอคติ ฮิสโตแกรม ทักษะ) · หลักฐานจากเรซูเม่พับได้
- **คิวรันพร้อมกัน 3 เธรด** (`QUEUE_WORKERS`) + ปลุก worker ทันทีที่ enqueue — วัดจริง 3 คน
  3m09s แทน 8m24s · ตัวเช็คโควตาอยู่ใต้ `_claim_lock` กันสามเธรดเห็นยอดเท่ากันแล้วใช้เกิน
- ไอคอนเว็บบนแท็บ `app/icon.svg` + `app/apple-icon.png` (แว่นขยายส่องคน)

### ชุดไฟล์ขึ้น cloud (2026-09-23 → 09-24)

`docker-compose.prod.yml` + `Caddyfile` + `frontend/Dockerfile.prod` + [DEPLOY.md](../DEPLOY.md)
(คู่มือทีละขั้นสำหรับคนไม่เคย deploy) · รูปแบบ: **VPS เครื่องเดียว + Postgres ใน compose + Caddy**
- ต้องรันชุดเดียวเท่านั้น (คิว/active_candidates/rate limit อยู่ในหน่วยความจำ)
- repo เป็น **public** ซึ่งทำให้ใช้ PyMuPDF (AGPL) บนเน็ตได้ถูกต้อง — แต่แปลว่าค่าใน
  `docker-compose.yml` ของ dev (`JWT_SECRET`, `ADMIN_PASSWORD`, รหัส Postgres) ใครก็อ่านได้
  ไฟล์โปรดักชันจึงไม่ประกาศความลับเลย (`environment:` ทับ `env_file:` เสมอ)
- CORS อ่านจาก `ALLOWED_ORIGINS` (`main.allowed_origins` ทิ้ง `*` และ `/` ท้าย) · หน้าเว็บกับ API
  อยู่โดเมนเดียว แยกด้วย `/api/*` จึงเป็น same-origin
- `NEXT_PUBLIC_API_BASE_URL` ฝังตอน build — เปลี่ยนโดเมนต้อง `--build` ใหม่
- ตรวจแล้ว: build อิมเมจหน้าเว็บผ่าน เสิร์ฟ 200 รันเป็น uid 1000 · **ยังไม่ได้ deploy จริง** รอ VPS + โดเมน
- ถามเรื่อง Supabase แล้วตัดสินใช้ Postgres ใน compose — Supabase ต้องแก้ checkpointer ต่อใหม่ได้
  (05_database ข้อ 2) และต่อพอร์ต 5432 ก่อน · ~~แพ็กเกจ `supabase` ใน requirements ไม่มีใครใช้~~ ถอดแล้ว 2026-10-12

### ตัวตรวจอคติ: ด่านกฎตายตัว + 8 หมวด (2026-09-28)

`agents/bias_rules.py` จับคำชัด ๆ ("เพศชาย", "อายุไม่เกิน 30 ปี", "สถานภาพโสด", "ส่วนสูง 160 ซม.")
ด้วย regex ก่อน/คู่กับ LLM — แน่นอนทุกรอบ ไม่เสีย call ถ้ากฎเจอแต่ LLM ตอบ passed จะบังคับ flagged
และแทน audit_log (กันข้อความขัดกันเอง) · ไม่ทำให้ลูป revise วน · prompt เพิ่มสถานภาพสมรส
รูปลักษณ์ ความพิการ สัญชาติ/ภูมิลำเนา และห้ามเขียน "ถอดออกแล้ว" กับเกณฑ์ที่ไม่เคยใช้คิดคะแนน
- **เข้มเรื่องเตือนผิด:** ไม่จับ "บุคลิกดี", "single", "native speaker", "สัญชาติไทย" เฉย ๆ,
  ประโยค "ไม่จำกัดเพศ อายุ…" · ประกาศจริง 13 ใบ: จับได้ 3 ใบที่มีอคติจริง เตือนผิด 0
- มีผลกับผู้สมัครใหม่เท่านั้น · ยังไม่ได้ทดสอบกับ Gemini จริง
- เจอระหว่างทาง: มี `nodes/jd_reviewer.py` ตรวจประกาศก่อนโพสต์อยู่แล้ว (ครอบคลุมสถานภาพสมรส/รูปลักษณ์)

### ตัวตรวจอคติ: ตรวจครั้งเดียวต่อตำแหน่ง (2026-09-28)

สิ่งที่ตัวตรวจดูเป็นของตำแหน่งทั้งหมด เดิมเรียก LLM ทุกผู้สมัคร = เสีย 1 call ต่อคนกับคำตอบเดียวกัน
ที่ยังต่างกันทุกรอบ และ HR รู้ว่าประกาศมีอคติหลังมีคนสมัครแล้ว ตอนนี้
- `POST /jobs/analyze` เรียก `bias_auditor.audit_jd` **ต่อจาก** `extract_jd` (ต้องเห็นรายการทักษะ) ·
  `ANALYZE_COST = 2` · AI ตรวจล้ม → ถอยไปกฎตายตัว analyze ไม่ล้ม
- ขั้นยืนยันเกณฑ์โชว์กล่อง "ประกาศนี้มีถ้อยคำที่อาจกีดกันผู้สมัคร" + ปุ่มกลับไปแก้ประกาศ (ไม่บล็อกการบันทึก)
- `create_job` คำนวณกฎใหม่ฝั่ง server เสมอ (client ส่งแค่ผลดิบของ LLM กลับมาเป็น `bias_llm`) แล้วเก็บ
  `jobs.jd_audit` · เกณฑ์ทักษะที่ HR ลบไปแล้วในขั้นยืนยันถูกกรองทิ้ง
- โหนด `bias_auditor` **ไม่เรียก LLM อีก** อ่าน `state["jd_audit"]` ที่ worker โหลดจากตำแหน่ง
  ไม่มี → กฎตายตัว · ลูป revise ยังทำงานจากผลของตำแหน่ง · ทุกคนในตำแหน่งได้ข้อความเดียวกันตรงตัว
- `COST_BY_KIND` process/reprocess **5 → 4** (ยังไม่ได้วัดซ้ำกับ Gemini) · `_DEFAULT_COST` เลิกเขียนเลข 5
  ตรง ๆ ใช้ `max(COST_BY_KIND.values())`
- ตำแหน่งเก่า 13 ใบเติม `jd_audit` แบบกฎอย่างเดียวแล้วด้วย `scripts/backfill_jd_audit.py --apply`
  (`--with-llm` = 1 call ต่อตำแหน่ง ยังไม่ได้รัน) · ผลประเมินเดิม 53 แถวไม่เปลี่ยน
- backup ก่อนแก้ schema: `backups/backup_before_jd_audit.sql`
- **ยังไม่ได้ทดสอบกับ Gemini จริง** และยังไม่ได้ดูกล่องเตือนในเบราว์เซอร์

### HR ยืนยันว่าถ้อยคำที่ถูกเตือน "จำเป็นกับงานนี้" (2026-09-28)

บางงานเพศหรือสัญชาติจำเป็นจริง (ตรวจค้นตัวผู้หญิง, อาชีพสงวนให้คนไทย) ถ้าไม่มีทางยืนยัน ⚠ ขึ้นในหน้า
ผู้สมัครทุกคนตลอดไปจนคนเลิกอ่านคำเตือน
- `jobs.bias_acknowledgements` `[{phrase, reason, by, at}]` แยกจาก `jd_audit` (ของเครื่อง vs การตัดสินใจของคน)
- `app/bias_ack.py`: `validate_acks` (เฉพาะถ้อยคำที่อยู่ในผลตรวจจริง · เหตุผล ≥ 10 ตัวอักษร ไม่ถึง = 422 ·
  ข้อเดิมเหตุผลเดิมคง by/at เดิม) · `bias_view` แยก pending/acknowledged — ยืนยัน**ทีละถ้อยคำ**
- ยืนยันได้สองที่: ขั้นยืนยันเกณฑ์ (`JobCriteriaConfirm.bias_acks`) และการ์ดในหน้าตำแหน่ง
  (`PUT /jobs/{id}/bias-acknowledgements` แทนทั้งชุด = เพิ่ม/ถอน) · ชื่อผู้ยืนยันมาจาก token
- **หน้าผู้สมัครอ่านผลตรวจจากตำแหน่งสด ๆ** (`CandidateDetail.job_bias`) แทน `audit_log` ของผลประเมิน —
  ยืนยันทีหลังผู้สมัครเก่าก็เห็นทันที โดยไม่เขียนทับบันทึกของตอนคัดกรอง · ผลข้างเคียง: ตำแหน่งเก่าที่
  ผลตรวจเป็นแบบกฎอย่างเดียวจะโชว์สำนวนของกฎแทนคำอธิบายของ AI เดิม (ถ้อยคำที่จับได้เหมือนกัน)
- ไม่มีผลกับคะแนนหรือกราฟ · เกณฑ์ทักษะที่มีอคติไม่ถูกปิดด้วยการยืนยันถ้อยคำ (ต้องแก้เกณฑ์เอง)
- backup ก่อนแก้ schema: `backups/backup_before_bias_ack.sql`
- **แก้ตามที่ลองจริง (2026-09-28):** ตำแหน่ง UI/UX Designer ประกาศ "เพศหญิง อายุไม่เกิน 35 ปี" —
  LLM รวมเป็นข้อเดียว แล้ว `merge_criteria` เดิมเก็บของ LLM การยืนยันครั้งเดียวจึงครอบทั้งเพศและอายุ
  ตอนนี้**ถ้อยคำของกฎเป็นหน่วยหลัก** ข้อของ LLM ที่ทับกฎถูกตัดส่วนที่กฎครอบออก เศษที่เหลือเก็บเฉพาะ
  เมื่อปรากฏตรงตัวในประกาศ (กันคำสรุปที่ LLM แต่งเอง) · แก้ตำแหน่งเดิมด้วย `scripts/resplit_jd_criteria.py`
  (ไม่เรียก LLM, เปลี่ยน 1 จาก 14) · การยืนยันเดิม "เพศหญิง อายุไม่เกิน 35 ปี" ไม่มีผลแล้ว ต้องยืนยันใหม่
  แยกข้อ — ไม่เดาแทนว่าเหตุผลหมายถึงเรื่องไหน · backup `backups/backup_before_resplit.sql`

### ตัวตรวจอคติข้อ 3: คำถามสัมภาษณ์ + อีเมล (2026-09-29)

**แก้ข้อเข้าใจผิด:** เคยบันทึกว่า "interview_planner เห็นเรซูเม่เต็ม" — ไม่จริง ไล่โค้ดแล้ว planner ได้แค่
ชื่อตำแหน่ง/ทักษะผ่าน-ขาด/ชื่อผู้สมัครเก่า drafter ได้แค่ชื่อผู้สมัคร+ชื่อตำแหน่ง ช่องโหว่แบบที่คิดไว้ไม่มี
- **ก.** `tests/test_prompt_privacy.py` ใส่ค่าส่วนตัวที่ค้นง่ายลงเรซูเม่ แล้วตรวจว่า prompt ของ planner/drafter
  (ทุกเส้นทางเชิญ/ปฏิเสธ) ไม่มีค่าเหล่านั้น — ใครเพิ่มเรซูเม่เข้า prompt ในอนาคตเทสต์ล้มทันที
- **ข.** ความเสี่ยงจริงคืออีเมลที่ HR แก้เอง/เทมเพลต · `bias_rules.find_biased_message_phrases` (กฎประกาศ +
  รูปประโยคในจดหมาย "เนื่องจากอายุ", "แต่งงานแล้วหรือยัง", "ตั้งครรภ์", "ศาสนาของท่าน") · ตรวจ**ในตัว**
  `send_candidate_email` → 409 `bias_warning` จนกว่า HR ยืนยัน · ส่งทั้งที่ถูกเตือน = log พร้อมชื่อผู้ใช้
- หน้าเว็บ: `api.ts` มี `ApiError` เก็บ status/detail (ข้อความ error รูปเดิม) + `biasWarningOf()` ·
  หน้าผู้สมัครขึ้น ConfirmDialog "กลับไปแก้ / ส่งต่อ"
- ไม่จับสวัสดิการ ("ลาคลอด", "ประกันครอบครัว"), "อายุงาน", ประโยค "ไม่จำกัดเพศ อายุ" · ร่างอีเมลของ AI
  ทุกฉบับในฐานข้อมูลและเทมเพลตปฏิเสธตั้งต้นไม่ถูกเตือน (มีเทสต์)
- ไม่ตรวจตอนบันทึกเทมเพลต (ถูกตรวจตอนส่งจริง)

### ตัวตรวจประกาศ: "คัดกรองได้ดีไหม" แทน "พร้อมโพสต์ไหม" (2026-09-29)

ผู้ใช้สังเกตว่าคำแนะนำเหมือนประกาศ JobsDB (เพิ่มสถานที่ทำงาน/ไฮบริด/เส้นทางเติบโต) — ต้นเหตุคือ prompt ของ
`jd_reviewer.py` ตั้งบทเป็นที่ปรึกษา "ก่อนนำไปโพสต์" และสั่งให้หาเรื่องพวกนั้นเอง ซึ่งไม่มีผลกับคะแนนเลย
- `JDReview` ใหม่: `unmeasurable` (ขยัน อดทน) · `vague_skills` (เก่งคอมพิวเตอร์) · `structure_issues`
  (ไม่แยกต้องมี/อยากได้, "React, Vue" กำกวม) · `must_have_review` · `posting_tips` (ความสำคัญต่ำสุด
  บรรทัดเล็กท้ายการ์ด) · **ตัด `bias_flags`** — ซ้ำกับตัวตรวจตอนกดวิเคราะห์ซึ่งแม่นกว่า
- prompt อธิบายวิธีให้คะแนนจริง ด้วยน้ำหนักจาก `matcher.REQUIRED_WEIGHT/PREFERRED_WEIGHT` ไม่เขียนเลขซ้ำ
- ปุ่มเปลี่ยนชื่อเป็น "ตรวจประกาศก่อนวิเคราะห์" · การ์ดบอกว่าเรื่องอคติตรวจตอนกดวิเคราะห์
- **ลองกับ Gemini จริง 3 ใบ (3 call):** HR Generalist ประกาศดี → เหลือแค่ "ระบุระดับภาษาอังกฤษ" ✓ ·
  ประกาศเขียนแย่ → จับครบทั้ง 4 ด้าน ✓ · Junior Web → นับประโยคในส่วน**หน้าที่**เป็น "วัดไม่ได้" ✗ แก้ prompt
  ให้ดูเฉพาะส่วนคุณสมบัติแล้ว · **ลองซ้ำแล้ว 2026-10-14 (1 call): ผ่าน** — `unmeasurable` 4 ข้อ มาจากส่วน Soft Skills
  ทั้งหมด (บรรทัด 27–30) ไม่มีข้อไหนจาก 5 บรรทัดในส่วนหน้าที่ (ตรวจด้วยสคริปต์ว่าข้อความที่ยกมาอยู่บรรทัดไหน)
  · ข้อความที่ยกมามีในประกาศจริงทุกข้อ · `posting_tips` ยังเสนอ "ระบุสถานที่ทำงาน" (ช่องความสำคัญต่ำสุด ตั้งใจให้มี)
  · **รอบสอง + HR Generalist (2 call): ผ่านทั้งคู่** — Junior Web รอบสองยก 4 ข้อเดิมแต่ตัดสั้นกว่า (ทุกข้อจากส่วนทักษะ)
    และเพิ่ม structure_issue ที่ถูก (Soft Skills ไม่ระบุต้องมี/อยากได้) · HR Generalist: unmeasurable 4 ข้อจากส่วนทักษะ
    (Interpersonal, Time Management, Native English speaker, เป็นคนไทย) ไม่มีจากส่วนหน้าที่ · vague_skills "HRIS Systems"
    (แนะนำระบุชื่อระบบ) ถูกต้อง · ~~ประกาศ HR Generalist ยังมีบรรทัดจากการทดลองอคติ~~ ลบแล้ว (หัวข้อถัดไป)

### ลบบรรทัดทดลองในประกาศ HR Generalist (2026-10-14, backup `backup_before_clean_hr_jd.sql`)
- `55a275a3`: ลบ 3 บรรทัดท้ายประกาศ "Native English speaker" / "English  ระดับ C2" / "เป็นคนไทย" (สคริปต์ตัดเฉพาะ 3 ข้อความนี้
  ตรงตัว ไม่ตรง 3 บรรทัดหยุดเอง) · ไม่มีปุ่มแก้ประกาศ จึง UPDATE raw_text ตรง
- ตรวจอคติใหม่ด้วย `_job_audit` + `audit_jd` (ทางเดียวกับตอนสร้างตำแหน่ง, 1 call) → passed, llm_checked
- ไม่แตะเกณฑ์/คะแนน/ai_criteria/jd_extraction · 3 บรรทัดไม่อยู่ในเกณฑ์อยู่แล้ว · 11 ตำแหน่งคะแนนขยับ 0
- ยังเตือนอยู่ (ไม่ได้แตะ): Sales Executive "เป็นคนไทย" (สร้าง 7 ต.ค. วันทดลองลูปอคติ — น่าจะทดลองเหมือนกัน)
  · Software Engineer / Backend Developer / UI/UX Designer เพศ+อายุ (ตัวอย่างสาธิตอคติที่ตั้งใจใส่)

### ข้อมูลและไฟล์สาธิต (2026-09-28)

- **แก้เกณฑ์ Junior Web Developer ตัว `346ef524`** ให้ตรงกับตัว `3243593d` — AI แตกเกณฑ์จากประกาศ
  เดิมไม่เท่ากัน (แยก GitHub/GitLab, เพิ่ม Agile/Scrum, Googling|Debugging) คนเดิมจึงได้ 47 แทน 60
  ทั้งที่ทักษะที่ตรงเท่ากัน · แก้ผ่าน `_save_criteria` (ไม่เรียก LLM) → 60/40 เท่ากันแล้ว ·
  backup `backups/backup_before_fix_jwd_criteria.sql`
- **`demo_resumes/` ขึ้น git แล้ว** — 11 PDF สมมติทั้งหมด (`@example.com`, `080-000-xxxx`) + `generate.py`
  + README บอกผลที่ควรเห็นต่อไฟล์ · ครอบคลุมเคสตามแผนทดสอบในบรีฟข้อ 7

### GitHub/GitLab/Bitbucket นับว่ารู้ Git (2026-10-06)
- เจอจริง: เรซูเม่เขียน "GitHub" แต่ required "Git" ถูกนับว่าขาด → เพิ่ม `IMPLIES` ทางเดียวใน `skills.py`
  (รู้ Git ไม่ได้แปลว่าเคยใช้ GitHub) · เทสต์ใน `test_skills.py::TestImplication`
- recompute `--apply`: คะแนนขึ้น 23/63 คน (Junior Web 40→47, 35→41 · AI Engineer 20→24) **ไม่มีใครข้ามแบนด์**
  · สำรองก่อนแก้ `backup_before_git_implies.sql`
- เรื่องเดียวกันที่ตอบผู้ใช้: "VS Code" กับ "Visual Studio Code" เป็นตัวเดียวกันอยู่แล้ว (ALIASES) — ชิปเทาในหน้าตำแหน่งคือเกณฑ์ "อยากได้" ไม่ใช่ "ขาด"

### ลูป revise ของ bias_auditor ยังไม่เคยวนในข้อมูลจริง (เช็ก 2026-10-06)
- `evaluations.bias_revision` ไม่ว่าง 0/63 · flagged 20 · ไม่มีตำแหน่งไหนมี `biased_*_skills`
- เหตุผล: jd_analyzer กรองเกณฑ์อคติออกจากรายการทักษะตั้งแต่ต้น ลูปเป็นตาข่ายชั้นสอง · หลักฐานว่าลูปทำงาน = `tests/test_bias_loop.py`
- ถ้าจะโชว์ของจริง: วิเคราะห์ประกาศทดลองก่อน (2 call) ดูว่า AI ชี้ทักษะไหม ค่อยสร้างตำแหน่ง + ส่งเรซูเม่ (4 call) — ยังไม่ได้ลอง

### ป้าย "คนเดียวกัน" ในผู้สมัครที่โปรไฟล์คล้ายกัน (2026-10-06)
- ที่มา: % เทียบ "รายการทักษะ" (query ของ retrieve_similar) กับ "เรซูเม่ทั้งฉบับ" → ไฟล์เดียวกันเป๊ะได้แค่ 78%
- `candidates.py::same_person` (บริสุทธิ์) — same_file: sha256 หรือ md5 ข้อความตรง · same_email: อีเมลในเรซูเม่ตรง
  คำนวณตอนเปิดหน้า (`_mark_same_person`) ผู้สมัครเดิมได้ป้ายทันที · แถวนั้นโชว์ป้ายแทน % ส่วนแถวอื่นยังโชว์ %
- `/candidates/search?relative_to=` ไม่คืนตัวเอง + ติดป้าย · เทสต์ `tests/test_same_person.py`
- แก้เทสต์ระเบิดเวลา `test_interview_schedule.py` (วันนัดตายตัว 2026-10-01 กลายเป็นอดีต) → อิงเวลาปัจจุบัน +30 วัน

### หน้าค้นหาผู้สมัคร: รวมคนเดียวกันเป็นแถวเดียว (2026-10-07)
- `GET /candidates/search/people` ค้นเวกเตอร์ 30 ไฟล์ → ดึงใบสมัครทั้งหมดของคนเหล่านั้น (sha/ข้อความ/อีเมล)
  → `group_people` (บริสุทธิ์, union-find ด้วย `same_person` ต่อกันเป็นทอด) · % = ค่าดีที่สุดของคนนั้น
- หน้า `/search`: ใบเดียว = หน้าตาเดิม · หลายใบ = "สมัคร N ครั้ง · X ตำแหน่ง" + ชิปทีละใบ (สูงสุด 4 + "อีก N ใบ")
  รวมด้วยอีเมลต้องบอก "(อีเมลตรงกัน)" เสมอ — ไม่มีใบสมัครไหนถูกซ่อน
- `/candidates/search` เดิมไม่แตะ (การ์ดค้นเพิ่มเติมในหน้าผู้สมัครยังแสดงทีละแถว + ป้ายคนเดียวกัน)
- ทดสอบความหมายภาษาพูด 2026-10-06 (6 embedding): 4/5 คำค้นเจอคนที่ถูกอันดับ 1, อีก 1 อันดับ 2 ·
  คำค้นที่ไม่มีใครตรง (นักบัญชี) ยังคืนคนมา top 58% vs ตรงจริง 62–67% → ตั้งเกณฑ์ตัดไม่ได้ · คลังมี ~17 ไฟล์

### ปิดช่องโหว่ทักษะอคติที่ HR พิมพ์เพิ่มเอง — แบบ ก. บล็อกตอนบันทึก (2026-10-07)
- เจอตอนทดลองให้ลูป revise วน: jd_analyzer กรอง "Native English speaker" ทิ้ง แต่ HR พิมพ์กลับเข้าช่องทักษะได้ → เข้าคะแนนเงียบ ๆ
- `bias_ack.biased_skills` (บริสุทธิ์ ไม่ใช้ AI): ตรงกับถ้อยคำที่ถูกเตือน (แยกส่วนในวงเล็บ, ต้องยาว ≥60% ของถ้อยคำ)
  หรือตัวทักษะเข้า `bias_rules` · ยืนยันถ้อยคำแล้ว = นับได้ · ไม่มีถ้อยคำให้ยืนยัน = ต้องลบ
- `create_job` และ `PUT /jobs/{id}/criteria` ตอบ 409 `biased_skill` · พรีวิวขึ้นเป็นคำเตือน · คืนค่าของ AI ไม่เช็ค
- เช็คเตือนผิดกับ 16 ตำแหน่ง 199 ทักษะ: 0 · หน้าสร้างตำแหน่งโชว์กล่องเตือนติดปุ่มบันทึก
- **ผู้ใช้จะลองเล่นก่อน ถ้าไม่ชอบเปลี่ยนเป็นแบบ ข.** = ไม่นับคะแนนอัตโนมัติ + ป้ายบนชิป (0 ขั้นตอนเพิ่ม)
  ใช้ `biased_skills` ตัวเดิมได้ แต่ต้องทำให้ "ไม่นับ" ทำงานทั้งตอนสร้าง แก้เกณฑ์ และตอนยืนยันทีหลัง (rescore)
- ยังค้าง: ทักษะที่ AI ชี้ (ลูป revise) ยังถูกตัดแม้ HR ยืนยันถ้อยคำแล้ว — ไม่สอดคล้อง แต่ยังไม่เคยเกิดจริง (0 ครั้ง)
- ผู้ใช้ลองแล้ว (2026-10-08) เลือกอยู่กับแบบ ก. แล้วปิด 2 จุดที่ตามมา:
  · **ถอนการยืนยันไม่ได้**ถ้าถ้อยคำนั้นยังเป็นทักษะในเกณฑ์ (`bias_ack.withdraw_blocked`, 409 biased_skill)
    ขวางเฉพาะที่เกิดจากการถอนครั้งนี้ ของค้างเก่าไม่ขวางการยืนยันข้ออื่น
  · การยืนยันที่เป็นทักษะด้วยได้ `scored: true` (คำนวณตอนแสดงจาก parsed_criteria) → ป้าย "นับเป็นทักษะในคะแนน"
    · ข้อความการ์ดเลิกบอกว่า "ไม่มีผลกับคะแนน" แบบเหมารวม
  · ต่อมา (ผู้ใช้ขอ): **ถอนแล้วลบออกจากเกณฑ์ได้ในคราวเดียว** — `PUT bias-acknowledgements` รับ `remove_skills`
    409 ตอบ `stripped_criteria` (bias_ack.strip_skills: ตัดเฉพาะตัวเลือกที่ตรงในกลุ่ม "A | B") → หน้าเว็บพรีวิวผลกระทบ
    → ConfirmDialog "คะแนนเปลี่ยน N คน · M คนเปลี่ยนกลุ่ม" → ส่งซ้ำพร้อม remove_skills · เขียนเกณฑ์+คะแนน+ถอน ในทรานแซกชันเดียว
    (`jobs._write_criteria` แยกจาก `_save_criteria`) · ผู้สมัครกำลังวิเคราะห์ = 409 ไม่เปลี่ยนอะไร
- ตัดสินใจ 2026-10-12: **ไม่มีปุ่ม "ลบ" คำเตือนถ้อยคำอคติ** — ลบได้โดยไม่มีเหตุผลทำให้ตัวตรวจไร้ความหมาย
  ทางปิดคำเตือนที่รับผิดชอบได้คือ "จำเป็นกับงานนี้" (เหตุผล+ใคร+เมื่อไร) · ทางที่ถูกกว่าในอนาคตคือปุ่ม "แก้ประกาศ"
  (แก้ raw_text แล้วกฎตรวจใหม่ฟรี) — ผู้ใช้ให้พักไว้
- **ConfirmDialog วาดผ่าน portal ไป document.body แล้ว** — `.glass-card` มี backdrop-filter ทำให้ fixed ยึดการ์ด
  (หนี้เดิม "dialog ซ้อนชั้นผิด" ส่วนของ ConfirmDialog ปิดแล้ว · hire-employee-dialog ยังไม่ได้เช็ก)

### ลบข้อมูลทดสอบซ้ำ (2026-10-12)
- สำรอง `backup_before_dedupe.sql` ก่อน · ลบผ่าน endpoint จริง (ด่านกัน + delete_thread ครบ)
- ตำแหน่ง 6: Junior Web ×4 (`281bc90c`, `43205fb3` + ระดับ 2 ที่เคยส่งอีเมล `3243593d`, `346ef524` — ผู้ใช้ยืนยัน
  ข้ามด่าน ประวัติส่งอีเมล 7 ฉบับหายถาวร) · Backend `507cf06b` · HR Officer ว่าง `a1a5b6ae`
- ผู้สมัครซ้ำในตำแหน่งเดียวกัน 3 ใบ (เก็บใบที่ตัดสินแล้ว) · ผลรวม: 18 → **12 ตำแหน่ง**, 71 → **42 ใบ**
- Kittipat หายจากระบบ (สมัครแค่ตำแหน่งที่ลบ) → ปรับคำตอบใน `eval_search.py` · ค่าฐานเท่าเดิม Hit@1 92% Hit@3 100%
- orphan checkpoint 3 thread ที่ `cleanup_dev_data.py` เจอ **มีอยู่ก่อนการลบครั้งนี้** (ไม่ใช่ผู้สมัครใน backup) — ลบแล้วรอบถัดไป

### เก็บหนี้เล็ก (2026-10-12, backup `backup_before_cleanup_debts.sql`)
- ลบ AI Engineer `7b44445d` (ผู้ใช้ยืนยัน — อีเมลส่งตอนทดลองระบบ) ผ่าน endpoint จริง ข้ามเฉพาะด่าน "เคยส่งอีเมล" →
  ผู้สมัคร 3 ใบ (Anan/Suda/Somchai — ยังมีใบอื่นในระบบ) + checkpoint 3 thread · **เก็บ `6c0d205a` ไว้ เพราะ `eval_resumes.py` ใช้**
  · เหลือ **11 ตำแหน่ง** · ค้นหายังเจอ: "อยากได้คนออกแบบกราฟิก" → Anan อันดับ 1, "Python, FastAPI" → Somchai อันดับ 2
- `cleanup_dev_data.py --apply --clear-stub-drafts`: orphan checkpoint 3 thread / 175 แถว + ร่างอีเมล stub ของ Anan → ไม่เหลือทั้ง 3 ข้อ
- ถอด `supabase` จาก requirements (ไม่มีโค้ดใช้) · build ใหม่ + pytest 1377 ผ่าน

### ล้างไฟล์ backup เก่า (2026-10-12)
- ทดสอบกู้ `backup_before_cleanup_debts.sql` ลงฐานชั่วคราว `restore_test` ก่อน: ไม่มี error, จำนวนแถวตรงกับที่คาด
  (มากกว่าของจริง 1 ตำแหน่ง / 3 ใบ / 6 thread = ส่วนที่เพิ่งลบ) แล้ว drop ฐานชั่วคราวทิ้ง
- ย้าย 18 ไฟล์ไป **Recycle Bin** (ไม่ลบถาวร): `backup_before_git_implies.sql` + ทั้งหมดใน `backups/` (17 ไฟล์ ก.ย.–ต.ค.)
  ชื่อ `backups/backup_before_*.sql` ที่อ้างในบันทึกด้านบนจึงไม่มีไฟล์อยู่แล้ว · **เก็บไว้ 2 ไฟล์**: `backup_before_cleanup_debts.sql`
  (ล่าสุด) และ `backup_before_dedupe.sql` (ก่อนลบข้อมูลซ้ำครั้งใหญ่) · โฟลเดอร์ `backups/` ว่างไว้ใช้ต่อ

### ลบเกณฑ์ "เป็นคนไทย" ที่ค้างจากการทดลอง (2026-10-13, backup `backup_before_remove_thai_criterion.sql`)
- Sales Executive `f63cc561`: AI จับ "เป็นคนไทย" ได้ถูก แต่วันทดลองลูปอคติ (7 ต.ค.) มีการกด "จำเป็นกับงานนี้" (admin, เหตุผล
  "คุยงานกับคนไทยบ่อย" — ที่จริงคือทักษะภาษา ไม่ใช่สัญชาติ) แล้วใส่เป็นทักษะต้องมี → เกณฑ์สัญชาติใช้คิดคะแนนผู้สมัคร 4 คน
- ผู้ใช้ยืนยันว่าเป็นข้อมูลทดลอง → `PUT /bias-acknowledgements` แบบ `remove_skills: true` (ถอน + ลบทักษะ + คำนวณใหม่ในคราวเดียว)
  · พรีวิวก่อน: 4 คน 0 → 0 ไม่ผ่านเท่าเดิม · ไม่มีอีเมลส่ง ไม่มีคำตัดสิน HR · คำเตือนในประกาศยังขึ้นตามเดิม (ไม่มีใครยืนยัน)
- ไม่แทนด้วย "ภาษาไทย": prompt ของ resume_parser (2026-10-13) ไม่ดึงภาษาที่ใช้สื่อสาร จะไม่มีใครผ่านข้อนั้น

### ทักษะที่ AI ชี้ว่ามีอคติ ยืนยันได้ (2026-10-14, backup `backup_before_bias_skill_ui_test.sql`)
- ช่องโหว่เดิม 2 ข้อ: (1) ลูปตัด `jd_audit.biased_*_skills` เสมอ HR ยืนยันไม่ได้ (2) ลบออกจากเกณฑ์แล้วคำเตือนไม่หาย
- `bias_ack.effective_biased_skills` ตัวเดียว ใช้ทั้งกราฟ (`audit_for_graph`) หน้าแก้เกณฑ์ (`rescore_job(exclusions=)`) และการ์ด
- ยืนยัน/ถอนทักษะที่ AI ชี้ = คำนวณคะแนนคนเดิมใหม่ · การ์ดพรีวิวผลกระทบก่อน (`POST .../bias-acknowledgements/preview`)
  ไม่มีใครคะแนนเปลี่ยน = บันทึกเลยไม่ถาม · ข้อที่เข้ากฎตายตัวด้วยถอนเฉย ๆ ไม่ได้ → ถอนพร้อมลบ (`removal_phrases`)
- บั๊กที่เจอระหว่างทำ: ยืนยันแล้วบันทึกเกณฑ์ไม่ได้ (ด่านทักษะ HR ไม่นับการยืนยันที่ชื่อทักษะ) · ถอนพร้อมลบไม่ลบอะไร
  (ทักษะไม่มีถ้อยคำให้อ้าง) · ลบทักษะแล้วหน้าผู้สมัครขึ้น "AI ชี้ว่ามีอคติ" คู่ "ผ่านเกณฑ์ความโปร่งใส" — แก้ครบ
- ลองบนหน้าเว็บด้วยตำแหน่งทดลอง (ลบทิ้งแล้ว): ยืนยัน → หน้าต่างผลกระทบ → คะแนนขยับทันที · ถอน · ถอนพร้อมลบ ·
  ลบทักษะแล้วการ์ดหาย · กล่องลูปในหน้าผู้สมัคร "HR ยืนยันภายหลัง" · มือถือ 375px ไม่ล้น
- ข้อมูลจริง 11 ตำแหน่ง 39 คน คะแนนขยับ 0 · ข้อสังเกต: ลบทักษะแล้วใส่กลับ การยืนยันเดิมกลับมาเอง (เก็บต่อตำแหน่ง)
  · ขั้นสร้างตำแหน่งลองบนหน้าจริงแล้ว (ดักเฉพาะ /jobs/analyze ด้วยคำตอบที่ endpoint จริงสร้างโดยแทนแค่ 2 ฟังก์ชัน AI
    — 0 call): ไม่ขึ้นปุ่มซ้ำ (ทักษะที่ตรงถ้อยคำในประกาศขึ้นที่เดียว) · ลบทักษะแล้วปุ่มหาย ใส่กลับแล้วกลับมา ·
    ไม่ยืนยันแล้วบันทึก = 409 ติดปุ่ม · มือถือไม่ล้น · **เจอบั๊กเก่า**: `_job_audit` กรองทักษะที่ AI ชี้ด้วย string
    ตรงตัว HR พิมพ์ "ใบขับขี่  ท.2" (เว้นสองที) แล้วคำเตือนหายทั้งข้อ การยืนยันถูกทิ้ง ทักษะถูกนับคะแนนเงียบ ๆ
    → แก้เป็นเทียบ canonical (`bias_ack.names_in_criteria`) + เทสต์ 2 ตัว · ข้อมูลจริงไม่โดน (ไม่มีตำแหน่งไหนมีทักษะที่ AI ชี้)

### LangSmith: error 16% มาจาก pytest + ปิด trace ตอนรันเทสต์ (2026-10-12)
- ไล่ trace 7 วัน (ไม่ใช้ AI): 308 trace, error 50 — **ทั้ง 50 คือ `RuntimeError('429 RESOURCE_EXHAUSTED')` ที่เทสต์จำลองเอง**
  (รันเทสต์ 1 ครั้ง = trace ~24 รายการ ผ่าน 19 + error 5 · เจอ 10 ครั้ง) · trace ที่เรียก Gemini จริง 62 รายการ **error 0**
- ตอบอาจารย์: "error ในหน้า LangSmith เป็นของเทสต์อัตโนมัติที่จำลองโควตาเต็ม การวิเคราะห์จริงไม่มี error"
- แก้: `tests/conftest.py` ปิด tracing เฉพาะ pytest (+ล้าง cache ของ SDK) · `tests/test_tracing_off.py` ล็อกไว้
  ยืนยัน: รันเทสต์ครบแล้ว trace ใหม่ = 0 · นอก pytest ยังเปิด · trace เทสต์เก่าหลุดหน้าสรุป 7 วันเองภายใน 19 ต.ค.

### ขึ้น VPS จริง + ส่งอีเมลผ่าน Gmail API (2026-10-15)
- DigitalOcean SGP1 `68.183.187.62` + `talentmatch-hr.duckdns.org` · Ubuntu 24.04 2GB + swap 2GB · ufw 22/80/443 · `up -d --build` ผ่าน (build ~275 วิ) · HTTPS Let's Encrypt จริง, /health, 401, http→https เช็คจากเครื่อง dev ผ่าน · ล็อกอิน + สร้างตำแหน่ง + ให้คะแนนเรซูเม่สมมติ ผ่าน · IMAP (993) ออกได้
- **ส่งอีเมล 502: DigitalOcean บล็อก 587/465 ขาออก** → เพิ่ม `EMAIL_TRANSPORT=gmail_api` ใน `email_sender.py` (urllib ล้วน, ขอ token ใหม่ทุกครั้ง, `invalid_grant`→503) + `scripts/gmail_oauth_setup.py` (PKCE+state, เขียน .env แบบ atomic chmod 600) · เทสต์ `test_email_gmail_api.py` 18 ตัว (รวม 1427) · dev ยังเป็น smtp · ขั้นตอน Google Cloud อยู่ใน DEPLOY.md ใต้ขั้นที่ 7
- เจอบั๊กคู่มือ: `openssl rand -base64` ทำ DATABASE_URL พังถ้ามี `/` → เปลี่ยนเป็น `-hex` แล้ว

## 🔜 ค้างอยู่ / ขั้นต่อไป (เรียงลำดับแนะนำ)

1. **Deploy จริง** — ฝั่งโค้ดพร้อมแล้ว (ดู "ชุดไฟล์ขึ้น cloud" ด้านบน) **รอผู้ใช้หา VPS + โดเมน**
   แล้วทำตาม [DEPLOY.md](../DEPLOY.md) · Hardening ที่เหลือ (ดู [04_security.md](04_security.md)):
   ~~TLS/reverse proxy~~ (Caddy แล้ว) · ~~backend รันเป็น root~~ (ผู้ใช้ `app` แล้ว 2026-10-12) ·
   ย้าย rate-limit ไป Redis · secrets manager · backup อัตโนมัติมีสคริปต์ใน DEPLOY.md ขั้นที่ 8 แต่ยังไม่ได้ตั้งจริง
   · **ซ้อมรัน `docker-compose.prod.yml` ในเครื่องผ่านแล้ว (2026-10-15, Gemini 0 call)** — โปรเจกต์แยก
   `talentmatch-rehearsal` + override ใน scratchpad (`env_file: !override` ไม่โหลด backend/.env จริง, Caddy ที่
   `talentmatch.localhost:8443`) ผ่าน: build, healthy ทั้ง 4 กล่อง (ว่างกินแรมรวม ~250MB), HTTPS + header,
   แยก /api, ล็อกอิน, สร้างตำแหน่งแบบไม่เรียก AI, อัป 1 ใบ → `deferred_quota`, ดูไฟล์ต้นฉบับตรงทุกไบต์,
   restart แล้วคิวอยู่, uid 1000, backup→กู้ลงกล่องชั่วคราวนับแถวตรง · ซ้อมไม่ได้: มือถือ (เบราว์เซอร์ในแอป
   ไม่เปิดใบรับรอง local) · เจอแล้วใส่ DEPLOY.md: quota `0` = ไม่จำกัด, ตัวอย่างเปิด LangSmith ไว้,
   กู้ได้เมื่อ `POSTGRES_USER` เหมือนเดิม
2. เคลียร์หนี้ dev: ~~job ที่ `parsed_criteria` เป็น NULL~~ (ปิดแล้ว), ~~แถวอีเมลที่โดน stub ทับ (subject='s')~~ (ล้างแล้ว 2026-10-12), reducer ของ HRSystemState
3. ~~ปรับปรุงความทนทาน: อัปโหลดหลายไฟล์แล้วชนโควตา~~ — **ปิดแล้ว 2026-09-10** ดู "คิวงานประมวลผล + คุมโควตา" ด้านล่าง
4. ~~ข้อมูล dev ค้าง: 2 งาน `parsed_criteria` = NULL~~ — **ปิดแล้ว 2026-09-02** ดู "เก็บกวาดข้อมูล dev" ด้านล่าง
5. ~~รับใบสมัครทางอีเมลอัตโนมัติ~~ — **ปิดแล้ว 2026-09-10 ครบทั้ง backend และ frontend** ดู "ปากทางรับใบสมัครทางอีเมล" ด้านล่าง · เหลือแค่ทดสอบกับกล่องเมลจริง ซึ่งต้องให้ผู้ใช้ทำเอง (ดู [03_environment.md](03_environment.md))
6. ~~PDF ภาษาไทยเพี้ยน~~ — **ปิดแล้ว** (PyMuPDF, พิสูจน์กับไฟล์จริง 2 ใบ ดูด้านบน)
7. ~~เฟส 4: กระดานติดตามผู้สมัคร + บันทึกผลสัมภาษณ์~~ — **ปิดแล้วครบทั้งสามส่วน 2026-09-12**
   ดู "กระดานติดตามผู้สมัคร" และ "บันทึกผลสัมภาษณ์จริง" ด้านบน · เหลือให้คนทดสอบการลาก
   ด้วยเมาส์จริงเอง
8. **เฟส 5: calibration** — ใช้ `interview_outcome` เทียบกับ `fit_score` เพื่อดูว่าคะแนน
   ของ AI แม่นแค่ไหน · **ยังทำไม่ได้ตอนนี้** ต้องรอข้อมูลสัมภาษณ์สะสมหลายเดือนก่อน
   ตอนนี้ทำได้แค่เก็บให้ครบทุกครั้งที่สัมภาษณ์
9. ~~**หนี้เล็ก ๆ ที่เจอตอนทำเฟส 4:**~~ — **ปิดแล้ว** ทั้งสองโมดัลใช้ `createPortal` แล้ว · โมดัลเดิม `hire-employee-dialog` กับ `confirm-dialog`
   ติดบั๊ก stacking context เดียวกับที่แก้ไปแล้วในโมดัลผลสัมภาษณ์ แต่ยังไม่แสดงอาการ
   เพราะกว้างแค่ `max-w-lg` — จะโผล่เมื่อจอแคบกว่า 1024px หรือมีใครขยายความกว้างมัน
   ทางแก้เดียวกัน คือ `createPortal` ไป `document.body`
10. **แถว `a8ce77b3` (Jeerawat Sakwong อีกแถว คะแนน 100) ค้างกลางทาง** — ไฟล์อัปซ้ำช่วงทดสอบ
    auto-advance ล้มสมัยก่อนมีคิว ผู้ใช้เลือก**ไม่แตะ** (2026-09-17) ตอนนี้หน้าเว็บขึ้นแถบ
    "หยุดกลางทาง" พร้อมปุ่มทำต่อ ถ้ากดจะกินราว 2 call · หรือลบทิ้งเป็นแถวซ้ำก็ได้
11. **ความเสี่ยงของฐานข้อมูล 12 ข้อ — เลื่อนไว้แก้ทีหลังตามที่ผู้ใช้ตัดสิน (2026-09-17)** ยังไม่ขวาง
    งานพัฒนา แต่ต้องแก้ก่อน deploy · รายละเอียด หลักฐาน และลำดับที่แนะนำอยู่ที่
    [05_database.md](05_database.md) (RLS ของ Supabase, checkpointer ต่อใหม่ไม่ได้, index/UNIQUE,
    ไม่มี migration, backup, PDPA)
12. **เกณฑ์ทักษะที่ AI ดึงจาก JD ผิด — ทางแก้ข้อ 1 (หน้าจอให้ HR แก้) และข้อ 2 (AI ติดป้าย +
    โค้ดจัดฝั่ง, `scripts/eval_jd_analyzer.py`) เสร็จ 2026-09-19 · ปุ่ม "ให้ AI อ่านประกาศใหม่"
    เสร็จ 2026-09-20** ยังเหลือ:
    ~~แก้เกณฑ์ AI Engineer~~ (ผู้ใช้แก้แล้ว 2026-09-20) · ~~ทางแก้ข้อ 3 กลุ่ม "ข้อใดข้อหนึ่ง"~~ (เสร็จ
    2026-09-20, `skills.alternatives`) · ตัวเลือกเดินกราฟใหม่
    อัตโนมัติที่ผู้ใช้เก็บไว้พิจารณา — เดิม: AI Engineer ทั้งสองตำแหน่ง
    นับตัวเลือกแบบ "or" เป็นข้อบังคับทุกตัว และเอาหน้าที่งานมาเป็นทักษะ คนที่ตรงคุณสมบัติครบอาจถูก
    ปฏิเสธอัตโนมัติ · หลักฐาน ทางแก้ 3 ระดับ และคำแนะนำ (ทำหน้าจอให้ HR แก้รายการทักษะก่อน
    วางแผนให้ผู้ใช้ดูก่อนลงมือ) อยู่ที่ [06_scoring_criteria.md](06_scoring_criteria.md)
13. **ลดขนาดฐานข้อมูล: ย้าย PDF/รูป ออกจาก BYTEA + ล้าง checkpoint ของเคสที่ปิดแล้ว —
    แผนละเอียดพร้อมแล้ว รอผู้ใช้ตัดสินใจ (2026-09-23)** ยังไม่เร่ง: วัดจริงได้ 25 MB จากเพดาน
    ฟรี 500 MB (ผู้สมัคร 47 คน ≈ 530 KB ต่อคน) ไฟล์กิน 46% ของฐาน checkpoint กิน 14%
    · **กับดักที่เจอตอนวางแผน:** `runner.resolve_graph_status()` คืน `"processing"` เมื่อไม่มี
    checkpoint ลบทิ้งเฉย ๆ แล้วหน้าเว็บจะขึ้น "กำลังวิเคราะห์…" ตลอดไป ต้องเพิ่มสถานะ
    `"archived"` ก่อนเสมอ · ขั้นตอน ข้อควรระวัง และคำถามที่ต้องตอบก่อนเริ่ม อยู่ที่
    [05_database.md](05_database.md) ข้อ 13
14. ~~**ตัวตรวจอคติ ไอเดียที่เสนอ 2026-09-26**~~ — **ปิดแล้วครบทั้ง 4 ข้อ (2026-09-29)** ข้อ 3 ทำเป็น
    เทสต์ล็อก prompt + ตรวจอีเมลตอนกดส่ง ดูหัวข้อด้านบน (ข้อความเดิมที่ว่า planner เห็นเรซูเม่เต็มนั้นผิด)
    · ยังไม่ทำโดยตั้งใจ: ตรวจคำถามที่ AI เขียน (AI ไม่มีข้อมูลให้ถาม โอกาสเจอต่ำ) และตรวจว่าคะแนนกลุ่มเพศใด
    ต่ำกว่า (ต้องเก็บเพศ/อายุผู้สมัครก่อน ขัดหลักของระบบ)
15. **แผนวัดผลตามบรีฟข้อ 7 ยังไม่ได้ทำ** — ชุดข้อมูลเฉลยใน LangSmith + รายงานความแม่นของการสกัดทักษะ
    ความเร็ว และค่า API ต่อการวิเคราะห์ มีแค่ `scripts/eval_jd_analyzer.py` · `demo_resumes/` เป็นจุดตั้งต้นได้

## ⚠️ กับดัก / บันทึกการตัดสินใจ
- **ต้องรัน/ทดสอบใน Docker เสมอ** (Smart App Control บล็อก binary wheels บน Windows — ดู 01)
- `backend/.env` ยังเป็น placeholder — ต้องใส่ `GOOGLE_API_KEY` จริงก่อนทดสอบส่วนที่เรียก LLM
- **[ตัดสินแล้ว] รันกราฟต่อผู้สมัคร, `thread_id = candidate_id`** — state ยังเป็น list (ยาว 1 ต่อรัน) รูปแบบตรงบรีฟ; ทำให้ HITL resume ต่อคนได้จริง แทนการ batch ทั้ง job
- **[ตัดสินแล้ว] router เป็น 3 ทางตาม CLAUDE.md** (บรีฟเขียน route แค่ 2 ทาง — CLAUDE.md ชนะ): <50 reject, ≥50 advance→interview_planner; ความต่าง >70 (auto) vs 50–70 (รอ HR) จัดการใน `runner.process_candidate` (auto-resume เมื่อ fit>70)
- **[ตัดสินแล้ว] JD analyzer รันครั้งเดียวตอน create_job** เก็บใน `jobs.parsed_criteria`; โหนด jd_analyzer จะ **ข้าม** ถ้า state มี `analyzed_jd` แล้ว (กันเรียก LLM ซ้ำต่อผู้สมัคร)
- **[ตัดสินแล้ว] persistence อยู่นอกโหนด** (ใน `runner.py`) เพื่อคงให้โหนดเป็น pure transformer; DB writes: evaluation (หลัง bias), interview_plan/email_draft (หลัง planner/drafter)
- `full_name` ของ candidate ตอนอัปโหลดตั้งชั่วคราวจากชื่อไฟล์ → `runner._persist_evaluation` อัปเดตเป็นชื่อจริงจาก parsed_resume แล้ว
- เคสรับ 50–70 แล้ว **rejected**: planner ถูก guard ให้ข้าม (คืน questions ว่าง), drafter ร่างอีเมลปฏิเสธ — ตัดสินจาก `hr_decision[cid]`
- **[แก้แล้ว] โมเดล Gemini:** บรีฟ/CLAUDE.md เขียน Gemini 1.5 Flash/Pro — **ใช้ไม่ได้ทั้งคู่**: 1.5 ปลดระวาง (404 NOT_FOUND) และ 2.5-pro บน free tier คืน 429 `limit: 0` (ไม่ใช่แค่ใช้เกิน — free tier ใช้ Pro ไม่ได้เลย) → [llm.py](../backend/app/agents/llm.py) ดีฟอลต์เป็น `gemini-2.5-flash` ทั้งสองชั้น, override ได้ด้วย `GEMINI_DEFAULT_MODEL`/`GEMINI_COMPLEX_MODEL`
- **[แก้แล้ว] log หายเงียบ:** uvicorn ไม่ตั้ง handler ให้ root logger → `log.exception` ใน background task หายไปหมด ทำให้ debug ยากมาก แก้ด้วย `logging.basicConfig()` ใน [main.py](../backend/app/main.py) — **อย่าลบออก**
- ถ้า background task เงียบ/ไม่มีผล: รัน node/runner ตรง ๆ ใน one-off container จะเห็น traceback ทันที (เร็วกว่าไล่ log)
- **โควตา Gemini free tier ต่ำมากและคิดแบบ "ต่อโมเดล"** (`GenerateRequestsPerDayPerProjectPerModel`): `gemini-2.5-flash` = **20 request/วัน** เท่านั้น ทดสอบ e2e รอบเดียวก็หมด อาการคือ background task เงียบแล้ว log ขึ้น 429 `RESOURCE_EXHAUSTED`
  - **ทางแก้เร็ว:** สลับโมเดลเพื่อได้โควตาก้อนใหม่ — ตอนนี้ [backend/.env](../backend/.env) ตั้ง `GEMINI_DEFAULT_MODEL`/`GEMINI_COMPLEX_MODEL` = `gemini-2.5-flash-lite` ไว้ (ทดสอบเคส rejected สำเร็จด้วยตัวนี้)
  - โมเดลที่คีย์นี้เรียกได้ (stable): `gemini-2.0-flash`, `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-2.5-pro`(โควตา 0), `gemini-3.5-flash`
- **PowerShell 5.1 `Invoke-RestMethod` ถอดรหัสไทยผิด** (อ่าน JSON เป็น Latin-1 เพราะ FastAPI ไม่ใส่ charset ใน Content-Type) — **ข้อมูลใน DB ถูกต้อง** ถ้าจะอ่านไทยให้ถูกใช้:
  `$b=(Invoke-WebRequest $url -UseBasicParsing).RawContentStream.ToArray(); [System.Text.Encoding]::UTF8.GetString($b) | ConvertFrom-Json`
- **อย่า pipe `curl.exe` เข้า `ConvertFrom-Json` ตรง ๆ** ใน PS 5.1 (output ถูกตัดเป็นบรรทัด → นับ/แปลงผิด) ให้ `Out-File` ก่อนแล้ว `Get-Content -Raw`
- `Invoke-RestMethod -Form` **ไม่มีใน PS 5.1** (มีใน PS7+) — อัปโหลดไฟล์ให้ใช้ `curl.exe -F`เมื่อมีคีย์
