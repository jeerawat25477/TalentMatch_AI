"""จุดรันแอปพลิเคชันหลักของ TalentMatch AI API (FastAPI).

- เปิด/ปิด connection pool และ init ตาราง (แอป + checkpointer) ผ่าน lifespan
- เปิด CORS ให้ frontend Next.js ที่ http://localhost:3000
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import close_pool, init_db
from app.routers import auth, candidates, employees, hr, jobs
from app.tracing import tracing_status

# uvicorn ไม่ตั้ง handler ให้ root logger — ถ้าไม่ตั้งเอง log จาก background task จะหายเงียบ
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()          # สร้างตารางแอป + ตาราง checkpoint* (idempotent)
    # รายงานว่า LangSmith tracing เปิดจริงไหม — ช่วยยืนยันว่า env ถูกอ่าน
    enabled, project = tracing_status()
    if enabled:
        log.info("LangSmith tracing เปิดอยู่ → project=%s", project)
    else:
        log.info("LangSmith tracing ปิด (ตั้ง LANGCHAIN_TRACING_V2=true + LANGCHAIN_API_KEY เพื่อเปิด)")
    yield
    close_pool()       # ปิด pool และ connection ของ checkpointer


app = FastAPI(title="TalentMatch AI API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # พอร์ตหน้าบ้าน Next.js — 3000 ตามสเปค, 4000 ใช้บน Windows ที่ 3000 ติด reserved range
    allow_origins=["http://localhost:3000", "http://localhost:4000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(candidates.router)
app.include_router(hr.router)
app.include_router(employees.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
