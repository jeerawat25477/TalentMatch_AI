"""จุดรันแอปพลิเคชันหลักของ TalentMatch AI API (FastAPI).

- เปิด/ปิด connection pool และ init ตาราง (แอป + checkpointer) ผ่าน lifespan
- เปิด CORS ให้ frontend Next.js (ดีฟอลต์ localhost, โปรดักชันตั้ง ALLOWED_ORIGINS)
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.audit import AuditMiddleware, purge_expired
from app.database import close_pool, init_db
from app.email_intake import intake_status_line, start_intake_worker, stop_intake_worker
from app.job_queue import reclaim_running
from app.queue_worker import start_worker, stop_worker
from app.routers import (
    audit,
    auth,
    candidates,
    email_templates,
    employees,
    hiring_board,
    hr,
    interview_outcome,
    job_offer,
    jobs,
    settings,
)
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
    # กู้งานที่ค้างจากโปรเซสที่ตายไป **ก่อน** สตาร์ต worker — ตอนนี้ไม่มีอะไรรันจริง
    # แถวที่ยังเป็น running จึงเป็นเศษแน่นอน (นี่คือกลไกที่ทำให้งานไม่หายตอนรีสตาร์ต)
    reclaim_running()
    purge_expired()    # ประวัติการใช้งานเก็บ 1 ปี (เรียกซ้ำตอนเปิดหน้าประวัติด้วย)
    start_worker()
    # ปากทางรับใบสมัครทางอีเมล — สตาร์ตเฉพาะเมื่อตั้ง IMAP_* ครบ และถึงสตาร์ตแล้วก็ยัง
    # ไม่แตะเมลจนกว่า HR จะเปิดสวิตช์ในหน้าตั้งค่า (ดีฟอลต์ปิด)
    log.info(intake_status_line())
    start_intake_worker()
    # รายงานว่า LangSmith tracing เปิดจริงไหม — ช่วยยืนยันว่า env ถูกอ่าน
    enabled, project = tracing_status()
    if enabled:
        log.info("LangSmith tracing เปิดอยู่ → project=%s", project)
    else:
        log.info("LangSmith tracing ปิด (ตั้ง LANGCHAIN_TRACING_V2=true + LANGCHAIN_API_KEY เพื่อเปิด)")
    yield
    stop_intake_worker()
    stop_worker()      # หยุด worker ก่อน ไม่งั้นมันจะไปใช้ pool ที่ปิดไปแล้ว
    close_pool()       # ปิด pool และ connection ของ checkpointer


app = FastAPI(title="TalentMatch AI API", lifespan=lifespan)

# ดีฟอลต์ = พอร์ตหน้าบ้าน Next.js ตอน dev (3000 ตามสเปค, 4000 ใช้บน Windows ที่ 3000
# ติด reserved range) โปรดักชันตั้ง ALLOWED_ORIGINS เป็นโดเมนจริง คั่นด้วยจุลภาค
#
# **ห้ามใส่ "*"** โดยเด็ดขาด: allow_credentials=True คู่กับ origin เป็น * เบราว์เซอร์จะ
# ปฏิเสธทุก request อยู่แล้ว และถ้าใช้ได้จริงก็เท่ากับเปิดให้เว็บใด ๆ ยิง API แทนผู้ใช้ที่
# ล็อกอินค้างอยู่ · ค่าที่กรองแล้วว่างจะถอยไปใช้ดีฟอลต์ ไม่ปล่อยให้ allow_origins เป็น []
# เงียบ ๆ เพราะนั่นทำให้หน้าเว็บใช้ไม่ได้ทั้งใบโดยไม่มี error บอกที่ backend
DEFAULT_ORIGINS = ["http://localhost:3000", "http://localhost:4000"]


def allowed_origins(raw: str | None) -> list[str]:
    """แปลงค่า ALLOWED_ORIGINS เป็นรายการ origin — ฟังก์ชันบริสุทธิ์เพื่อทดสอบได้ตรง ๆ.

    ตัดช่องว่างและ / ท้ายสุดออก (Origin header ของเบราว์เซอร์ไม่มี / ท้าย ถ้าตั้งมาเกิน
    มันจะไม่ตรงแล้วโดนบล็อกทั้งที่ตั้งค่าถูก) · ทิ้ง "*" ทิ้งเสมอ · ว่าง = ใช้ดีฟอลต์
    """
    items = [o.strip().rstrip("/") for o in (raw or "").split(",")]
    return [o for o in items if o and o != "*"] or DEFAULT_ORIGINS


ALLOWED_ORIGINS = allowed_origins(os.getenv("ALLOWED_ORIGINS"))
log.info("CORS อนุญาต origin: %s", ", ".join(ALLOWED_ORIGINS))

# ประวัติการใช้งาน — เพิ่มก่อน CORS เพื่อให้ CORS อยู่ชั้นนอกสุด (ตอบ preflight ก่อนถึงตัวจด)
app.add_middleware(AuditMiddleware, routes_provider=lambda: app.routes)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(candidates.router)
app.include_router(hr.router)
app.include_router(employees.router)
app.include_router(email_templates.router)
app.include_router(settings.router)
app.include_router(hiring_board.router)
app.include_router(interview_outcome.router)
app.include_router(job_offer.router)
app.include_router(audit.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
