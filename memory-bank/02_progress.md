# Memory Bank — 02: ความคืบหน้า (สถานะล่าสุด)

> อัปเดตล่าสุด: 2026-08-02 (วงจรชีวิตตำแหน่งงาน: ปิดรับสมัคร + ลบถาวร) · แก้ไฟล์นี้ทุกครั้งที่ทำงานเสร็จเป็นก้อน

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
- ⚠️ **ยังไม่ได้ยืนยัน mobile drawer ด้วยตาจริง** — headless บน Windows ย่อ viewport ต่ำกว่า ~500px ไม่ได้ (ดู 03); ยืนยันได้แค่ว่า hamburger โผล่และ sidebar ซ่อนตอน viewport < 768

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
  - หมายเหตุ: ยังมี orphan checkpoint 5 แถวของ thread `566187c1…` **ค้างมาจากก่อนหน้านี้** (ไม่ได้เกิดจากฟีเจอร์นี้) ถ้าอยากสะอาดต้องลบมือ

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

## 🔜 ค้างอยู่ / ขั้นต่อไป (เรียงลำดับแนะนำ)

1. **[feature — multi-agent] ลูป bias_auditor → matcher (critique → revise)** — ทำให้เป็น agent loop จริง
   - **เงื่อนไขสำคัญ (คุมโควตา):** cap รอบไว้ **1 รอบ** และเข้าลูป **เฉพาะเคสที่ bias_auditor flag จริง** (`audit_status="flagged"`) ไม่ใช่ทุกคน → เปลือง chat call เพิ่มเฉพาะเคสมีปัญหา
   - เมื่อ flag: auditor เสนอ "ทักษะ/เกณฑ์ที่อาจมีอคติ" → ตัดออกจาก JD/skills → ให้ matcher (deterministic, ฟรี) คำนวณใหม่ → ตรวจซ้ำ 1 ครั้ง
   - ⚠️ **คุณค่าจริงมีจำกัด** (บันทึกไว้ตอนวิเคราะห์): คะแนนมาจาก matcher ที่ดูแค่ทักษะอยู่แล้ว ไม่มีเพศ/อายุ/สถาบัน → อคติในคะแนนแทบไม่มีให้แก้ · ประโยชน์หลักคือจับอคติใน "ตัว JD" + โชว์ agent loop สำหรับรายงาน
   - ต้องเพิ่ม conditional edge หลัง bias_auditor (flagged → กลับ matcher, ไม่งั้น → router เดิม) + counter กันวนเกิน 1 · ระวังกระทบ HITL/checkpointer (รูปกราฟเปลี่ยน)
2. Hardening ที่เหลือก่อน deploy (ดู checklist ใน [04_security.md](04_security.md)): TLS/reverse proxy · non-root container · ย้าย rate-limit ไป Redis · secrets manager
3. เคลียร์หนี้ dev: job ที่ `parsed_criteria` เป็น NULL, แถวอีเมลที่โดน stub ทับ (subject='s'), reducer ของ HRSystemState
4. ปรับปรุงความทนทาน: Gemini คืน 503 เป็นระยะ (SDK retry ให้เอง) และ free tier มีโควตาต่ำมาก — ถ้าอัปโหลดทีละหลายไฟล์จะชนลิมิตแน่ ควรคุม concurrency/backoff หรืออัปเกรดแพลน
5. ข้อมูล dev ค้าง: มี 2 งาน (`Python Developer`, `Senior Python Developer` ตัวซ้ำ) ที่ `parsed_criteria` เป็น NULL แต่มี evaluation คะแนน 100/40 ค้างจากตอนทดสอบยุคแรก — ถ้าอยากให้สะอาดต้องลบทิ้ง (guard ใหม่ใน matcher กันไม่ให้เกิดเคสนี้ซ้ำแล้ว)
6. **[ค้าง — ผู้ใช้เลือก "ปล่อยไว้ก่อน" 2026-08-10] สกัดข้อความ PDF ภาษาไทยเพี้ยน** — `pdfplumber` เรียง glyph ตามพิกัด x ทำให้สระ/วรรณยุกต์ซ้อน (◌ี ◌ั ◌์) สลับตำแหน่ง (เช่น `จีรวัฒน์` → `จรี วัฒน์`, `ศักดิ์` → `ศักดิ`). กระทบเฉพาะข้อความไทย (Latin สกัดถูก) → ชื่อ/การศึกษาเพี้ยน แต่ทักษะ/คะแนนไม่กระทบ. ทางแก้ที่ได้ผล: สลับ engine เป็น **pypdfium2** (license เสรี, อ่านตาม content stream) หรือ PyMuPDF (เก่งกว่าแต่ AGPL) ใน [utils/pdf_extractor.py](../backend/app/utils/pdf_extractor.py) — ต้อง rebuild backend + เพิ่ม dependency

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
