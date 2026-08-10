# Memory Bank — 03: สภาพแวดล้อม & คำสั่งรัน

> เครื่อง dev: Windows 11, PowerShell + Docker Desktop (v29.6.1). **รันทุกอย่างผ่าน Docker**

## คำสั่งที่ใช้บ่อย

### เปิด/ปิดระบบ
```powershell
docker compose up -d              # เปิด db + backend (backend hot-reload)
docker compose up -d db           # เปิดเฉพาะ Postgres
docker compose logs -f backend    # ดู log backend
docker compose down               # ปิด (ข้อมูลคงอยู่ใน volume pgdata)
docker compose down -v            # ปิด + ลบข้อมูล DB
```

### rebuild หลังแก้ requirements.txt / Dockerfile
```powershell
docker compose build backend      # ถ้า Docker Hub timeout: docker pull python:3.12-slim ก่อน
```
> โค้ดใน `backend/` mount เข้า container (`./backend:/app`) → แก้ `.py` แล้วเห็นผลทันทีด้วย `--reload` โดยไม่ต้อง rebuild
> rebuild จำเป็นเฉพาะตอนเปลี่ยน dependencies เท่านั้น

### รันคำสั่ง/ทดสอบใน container (one-off)
```powershell
docker compose run --rm backend python -c "import psycopg; print('ok')"
docker compose run --rm --no-deps backend python -c "..."   # ไม่ต้องรอ db
```

### เทส + สคริปต์บำรุงข้อมูล (ไม่เรียก LLM ทั้งคู่ จึงไม่กินโควตา Gemini)
```powershell
docker compose exec -T backend python -m pytest tests/ -q                    # เทสการเทียบทักษะ
docker compose exec -T backend python scripts/recompute_scores.py            # ดูผลก่อน (dry-run)
docker compose exec -T backend python scripts/recompute_scores.py --apply    # คำนวณคะแนนใหม่จริง
docker compose exec -T backend python scripts/backfill_embeddings.py         # index resume ที่ยังไม่มีเวกเตอร์
docker compose exec -T backend python scripts/backfill_embeddings.py --all   # index ใหม่ทั้งหมด
```
> `backfill_embeddings` เรียกเฉพาะ embedding API ซึ่งมีโควตา **แยกจาก** generateContent

### เข้าดู DB
```powershell
docker compose exec -T db psql -U talentmatch -d talentmatch -c "\dt"
docker compose exec -T db psql -U talentmatch -d talentmatch -c "\dx vector"   # เช็ค pgvector
```
> อิมเมจ db คือ **`pgvector/pgvector:pg16`** (ไม่ใช่ `postgres:16-alpine` แล้ว) — จำเป็นสำหรับ extension `vector`
> เคยสลับจาก alpine (musl) มา Debian (glibc) บน volume เดิม: PG major เท่ากันจึงอ่านข้อมูลเก่าได้ปกติ
> แต่ถ้าจะสลับอิมเมจอีกครั้ง **สำรองก่อนเสมอ**: `docker compose exec -T db pg_dump -U talentmatch -d talentmatch --clean --if-exists | Out-File backup.sql -Encoding utf8`
> db **ไม่ได้ publish พอร์ต 5432 ออก host** แล้ว — backend ต่อผ่าน network ภายใน (`db:5432`)
> เหตุผล: ช่วงพอร์ตที่ Windows/WinNAT จองไว้ **เปลี่ยนทุกครั้งที่รีบูต** (เคยชน 5432 จน `up` ล้ม)
> เช็คช่วงที่ถูกจอง: `netsh interface ipv4 show excludedportrange protocol=tcp`

### ดูหน้าเว็บจริงแบบ headless (ตรวจงาน UI)
หน้าเว็บเป็น client component + SWR → SSR คืนแค่ "กำลังโหลด…" การเช็ค HTTP 200 **ไม่พอ** ต้องเรนเดอร์จริง:
```powershell
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
Start-Process $edge -ArgumentList @("--headless","--disable-gpu","--no-sandbox",
  "--user-data-dir=$env:TEMP\shot\p","--window-size=1440,1600","--virtual-time-budget=15000",
  "--screenshot=$env:TEMP\shot\page.png","http://localhost:4000/") -Wait -NoNewWindow
```
(ต้องใส่ `--virtual-time-budget` ไม่งั้นจับภาพก่อน SWR โหลดเสร็จ)
> ⚠️ `--window-size` แคบ ๆ (เช่น 430) **ทดสอบ mobile ไม่ได้จริง** — Edge บน Windows มีความกว้างหน้าต่างขั้นต่ำ
> ภาพจึงเป็นการ crop จาก viewport ที่กว้างกว่า (ดูเหมือนเนื้อหาล้นขอบ ทั้งที่ไม่ได้ล้น)
> ถ้าต้องทดสอบ mobile จริงต้องใช้ CDP `Emulation.setDeviceMetricsOverride`

## MailHog (SMTP ปลอมสำหรับ dev — http://localhost:8025)
- `docker compose up -d mailhog` (ขึ้นอัตโนมัติกับ `up`) · backend ต่อผ่าน `mailhog:1025` ภายใน
- กดส่งอีเมลในหน้า deep dive แล้วมาดูที่ UI นี้ — ไม่ส่งออกอินเทอร์เน็ตจริง เหมาะทดสอบโดยไม่ต้องมี Gmail creds
- ดูอีเมลผ่าน API: `GET http://localhost:8025/api/v2/messages`

## Frontend (Next.js — http://localhost:4000)
> ⚠️ host port = **4000** ไม่ใช่ 3000 — พอร์ต 3000 อยู่ในช่วง reserved ของ Windows/WinNAT (`netsh interface ipv4 show excludedportrange protocol=tcp` → 2996–3095) bind ไม่ได้ · container ยัง listen 3000 ภายใน · backend CORS อนุญาตทั้ง :3000 และ :4000
- `docker compose up -d frontend` — Next dev (hot-reload, mount `./frontend`)
- `docker compose build frontend` — เมื่อแก้ package.json
- `docker compose logs -f frontend` — ดู compile/log
- โค้ดอยู่ใน `frontend/` (App Router + TS + Tailwind + SWR); design token อยู่ใน [../frontend/DESIGN.md](../frontend/DESIGN.md)
- เบราว์เซอร์เรียก backend ตรงที่ `NEXT_PUBLIC_API_BASE_URL=http://localhost:8080` (ตั้งใน compose)
- ⚠️ backend published บน host **:8080** (ไม่ใช่ 8000) — พอร์ต 8000 อยู่ในช่วง 7909-8008 ที่ WinNAT จอง จึง bind ไม่ได้บน Windows (อาการเดียวกับ 3000→4000) คอนเทนเนอร์ยังฟังที่ 8000 ภายใน

## Endpoints (backend ที่ http://localhost:8080)
> ⚠️ ทุก endpoint (ยกเว้น `/health` และ `/auth/login`) ต้องมี header `Authorization: Bearer <token>` — ไม่มี = **401**
- `GET  /health`                                   (เปิด ไม่ต้อง auth)
- `POST /api/v1/auth/login`                         body: `{"username":"...","password":"..."}` → `{access_token}` (เปิด)
- `GET  /api/v1/auth/me`                            คืน username ของ token ปัจจุบัน
- `POST /api/v1/jobs`                              body: `{"raw_text": "..."}`
- `GET  /api/v1/jobs`                              list งานทั้งหมด + candidate_count (หน้าเลือกงาน)
- `GET  /api/v1/jobs/{job_id}`
- `POST /api/v1/jobs/{job_id}/resumes`             multipart form field `files` (PDF หลายไฟล์) → 202
- `GET  /api/v1/jobs/{job_id}/candidates`          เรียงตาม fit_score
- `GET  /api/v1/candidates/search?q=&limit=`       ค้นหาเชิงความหมาย (pgvector) — **ประกาศก่อน route ล่างเสมอ**
- `GET  /api/v1/candidates/{candidate_id}`
- `POST /api/v1/candidates/{candidate_id}/decision` body: `{"decision":"approved|rejected","notes":"..."}`
- `POST /api/v1/candidates/{candidate_id}/email/send`  body: `{"to":"...","subject":"...","body":"..."}` (ส่ง sync)
- Swagger UI: http://localhost:8080/docs
- **MailHog UI: http://localhost:8025** — ดูอีเมลที่ระบบส่ง (dev, SMTP ปลอม ไม่ส่งออกจริง)

## ล็อกอิน (dev)
- ผู้ใช้เริ่มต้น: **`admin` / `admin1234`** (ตั้งใน docker-compose — prod เปลี่ยนผ่าน `.env`)
- ขอ token: `POST /api/v1/auth/login` แล้วแนบ `Authorization: Bearer <token>` ทุก request
```powershell
$tok = (Invoke-RestMethod http://localhost:8080/api/v1/auth/login -Method Post -ContentType 'application/json' -Body '{"username":"admin","password":"admin1234"}').access_token
Invoke-RestMethod http://localhost:8080/api/v1/jobs -Headers @{ Authorization = "Bearer $tok" }
```
> rate-limit: ล็อกอินผิด 5 ครั้งต่อ (IP+username) ใน 5 นาที → 429 · restart backend เคลียร์ (เก็บใน memory)

## ตัวอย่างทดสอบเร็ว (PowerShell)
```powershell
$tok = (Invoke-RestMethod http://localhost:8080/api/v1/auth/login -Method Post -ContentType 'application/json' -Body '{"username":"admin","password":"admin1234"}').access_token
$H = @{ Authorization = "Bearer $tok" }
$job = Invoke-RestMethod http://localhost:8080/api/v1/jobs -Method Post -ContentType 'application/json' -Headers $H -Body '{"raw_text":"Senior Python Dev, 3y, FastAPI"}'
Invoke-RestMethod "http://localhost:8080/api/v1/jobs/$($job.id)/candidates" -Headers $H
```
> หมายเหตุ: `Invoke-RestMethod -Form` รายงาน status code ของ error ไม่ชัด — ตรวจ HTTP status ด้วย `curl.exe -s -o NUL -w "%{http_code}"` แทน

## Environment variables ([backend/.env](../backend/.env))
- `GOOGLE_API_KEY` — Gemini (ตอนนี้ = `changeme`, **ต้องใส่ค่าจริงก่อนทดสอบ LLM**)
- `SUPABASE_DB_URL` — connection string โปรดักชัน (Supabase)
- `DATABASE_URL` — ตั้งใน docker-compose ชี้ไป Postgres ในคอมโพส (`postgresql://talentmatch:talentmatch@db:5432/talentmatch`); `database.py` เลือก `DATABASE_URL` ก่อน แล้ว fallback เป็น `SUPABASE_DB_URL`
- `LANGCHAIN_TRACING_V2` / `LANGCHAIN_API_KEY` / `LANGCHAIN_PROJECT` — LangSmith tracing (ตั้งครบ = เปิดเอง)
  · เปิดอยู่จะเห็น log ตอนบูต "LangSmith tracing เปิดอยู่ → project=..." · trace ติดป้าย `screen-candidate-<id>` + tag `talentmatch`
  · แก้ `.env` แล้วต้อง `docker compose up -d backend` ให้โหลดใหม่
- `RAG_ENABLED` (true) / `RAG_TOP_K` (3) — retrieval agent หาผู้สมัครคล้ายกัน · false = โหนด no-op · ใช้ embedding quota (แยกจาก chat)
- `EMBEDDING_MODEL` / `EMBEDDING_DIM` — คลังเวกเตอร์ (ดีฟอลต์ `models/gemini-embedding-001` / `768`)
  ⚠️ `EMBEDDING_DIM` ต้องตรงกับ `VECTOR(n)` ใน `app/schema.sql` และถ้าเปลี่ยนต้อง index ใหม่ทั้งหมด
  ⚠️ `models/text-embedding-004` ตามบรีฟ **เรียกไม่ได้แล้ว** (ไม่อยู่ใน ListModels ของคีย์นี้)
- `SMTP_HOST/PORT/STARTTLS/FROM/USER/PASSWORD` — ส่งอีเมล · dev: compose ตั้งชี้ MailHog ให้แล้ว (ไม่ต้องตั้งเอง)
  prod: ใส่ค่า SMTP จริงใน `.env` (Gmail ต้องเปิด 2FA + App Password) · `USER/PASSWORD` มีเมื่อ SMTP ต้อง auth
- `MAX_UPLOAD_MB` (10) / `MAX_FILES` (20) — ลิมิตอัปโหลดกัน DoS
- `JWT_SECRET` (**จำเป็น** ไม่มีดีฟอลต์) / `JWT_EXPIRE_HOURS` (12) — auth · prod ใช้ค่าสุ่มยาว (`openssl rand -hex 32`)
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` — ผู้ใช้เริ่มต้นที่ seed ตอนบูต · `LOGIN_MAX_FAILS` (5) / `LOGIN_FAIL_WINDOW_SEC` (300)

## เวอร์ชันแพ็กเกจหลัก (ยืนยันใน Docker)
fastapi 0.139.0 · langgraph 1.2.9 · langchain 1.3.13 · pydantic 2.13.4 · psycopg 3.3.4 · pdfplumber 0.11.10 · supabase 2.31.0 · Postgres 16
