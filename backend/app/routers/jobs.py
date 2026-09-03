"""เราเตอร์ตำแหน่งงาน (Job Description)."""
import logging
import os
import time

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Json

from app.agents.nodes import analyze_jd
from app.agents.nodes.jd_reviewer import review_jd
from app.agents.runner import active_candidates
from app.agents.models import JDReview
from app.auth import get_current_user
from app.rate_limit import hit_and_check, retry_after_sec
from app.database import get_checkpointer, get_conn
from app.schemas import (
    JDReviewIn,
    JobCreate,
    JobDeleteOut,
    JobListItem,
    JobOut,
    JobStatusUpdate,
)

# คอลัมน์ที่ทุก endpoint คืนเป็น JobOut — รวมไว้ที่เดียวกันเผื่อเพิ่มฟิลด์ทีหลัง
_JOB_COLS = "id, title, raw_text, parsed_criteria, status, closed_at, created_at"

log = logging.getLogger(__name__)

# กันทั้ง router ด้วย JWT — ทุก path ต้องล็อกอินก่อน
router = APIRouter(
    prefix="/api/v1/jobs", tags=["jobs"], dependencies=[Depends(get_current_user)]
)


@router.get("", response_model=list[JobListItem])
def list_jobs() -> list[JobListItem]:
    """รายการงานทั้งหมด (ใหม่ก่อน) พร้อมจำนวนผู้สมัคร — สำหรับหน้าเลือกงาน."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT j.id, j.title, j.raw_text, j.parsed_criteria,
                   j.status, j.closed_at, j.created_at,
                   count(c.id) AS candidate_count
            FROM jobs j
            LEFT JOIN candidates c ON c.job_id = j.id
            GROUP BY j.id
            ORDER BY j.created_at DESC
            """
        ).fetchall()
    return [JobListItem(**r) for r in rows]


@router.post("", response_model=JobOut, status_code=201)
def create_job(payload: JobCreate) -> JobOut:
    """รับ JD ดิบ บันทึกลงฐานข้อมูล และ (ต่อไป) ส่งให้ JD Analyzer สกัดเกณฑ์.

    ตอนนี้บันทึกแถวงานพร้อม title ชั่วคราว; parsed_criteria จะถูกเติมโดย
    โหนด jd_analyzer ในเลเยอร์ agents/ เมื่อกราฟถูกสร้าง.
    """
    # รัน JD Analyzer เติม parsed_criteria + title จริง (graceful ถ้า LLM ล้มเหลว/ไม่มีคีย์)
    fallback_title = payload.raw_text.strip().splitlines()[0][:255] or "Untitled Position"
    analyzed: dict | None = None
    try:
        analyzed = analyze_jd({"raw_jd": payload.raw_text, "analyzed_jd": None}).get("analyzed_jd")
    except Exception as exc:  # noqa: BLE001 — อย่าให้ endpoint ล้มเพราะ LLM
        log.warning("jd_analyzer ล้มเหลว จะบันทึกงานโดยยังไม่มี parsed_criteria: %s", exc)

    title = (analyzed or {}).get("job_title") or fallback_title
    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO jobs (title, raw_text, parsed_criteria)
            VALUES (%s, %s, %s)
            RETURNING """
            + _JOB_COLS,
            (title, payload.raw_text, Json(analyzed) if analyzed else None),
        ).fetchone()
        conn.commit()
    return JobOut(**row)


# เพดานการกด "ตรวจ JD" ต่อผู้ใช้ต่อนาที — คุมโควตา LLM ไม่ใช่กันโจมตี
# HR แก้ JD แล้วกดตรวจซ้ำได้หลายรอบตามธรรมชาติ แต่กดรัว ๆ จะกินโควตาฟรี 20/วันหมดโดยไม่ตั้งใจ
JD_REVIEW_MAX_PER_MIN = int(os.getenv("JD_REVIEW_MAX_PER_MIN", "5"))
_JD_REVIEW_WINDOW_SEC = 60.0
_jd_review_hits: dict[str, list[float]] = {}


@router.post("/review-jd", response_model=JDReview)
def review_job_description(
    payload: JDReviewIn, user: str = Depends(get_current_user)
) -> JDReview:
    """ตรวจร่างประกาศก่อนโพสต์ แล้วคืนคำแนะนำ — **ไม่บันทึกอะไรลงฐานข้อมูล**.

    เป็นพรีวิวล้วน ๆ: HR จะแก้ตามหรือไม่ก็ได้ แล้วค่อยกด POST /api/v1/jobs สร้างงานจริง
    (คนละจังหวะกับ jd_analyzer ที่รันหลังสร้างงานไปแล้ว)

    ⚠️ ประกาศไว้ก่อน /{job_id} ตามธรรมเนียม literal-ก่อน-พารามิเตอร์ ตอนนี้ยังไม่มี
    POST /{job_id} จึงไม่ชนจริง แต่กันไว้เผื่อมีคนเพิ่มทีหลัง (บทเรียนจาก /candidates/search)

    LLM ล้มเหลว → 503 ไม่ใช่กลืน error แบบ create_job เพราะพรีวิวไม่มีอะไรให้ degrade
    ต่างจากการสร้างงานที่ยังบันทึกแถวได้แม้ยังไม่มี parsed_criteria
    """
    # ตรวจเพดานก่อนเสมอ — ยังไม่เสียโควตา LLM ถ้าถูกปฏิเสธตรงนี้
    now = time.time()
    if not hit_and_check(
        _jd_review_hits, user, now, JD_REVIEW_MAX_PER_MIN, _JD_REVIEW_WINDOW_SEC
    ):
        wait = retry_after_sec(_jd_review_hits, user, now, _JD_REVIEW_WINDOW_SEC)
        raise HTTPException(
            status_code=429,
            detail=(
                f"ตรวจ JD ได้ไม่เกิน {JD_REVIEW_MAX_PER_MIN} ครั้งต่อนาที "
                f"(กันโควตา AI หมดโดยไม่ตั้งใจ) — ลองใหม่ในอีก {wait} วินาที"
            ),
        )

    try:
        return review_jd(payload.raw_text)
    except Exception as exc:  # noqa: BLE001 — โควตาหมด/คีย์ผิด ไม่ควรเป็น 500 เปล่า ๆ
        log.exception("ตรวจ JD ไม่สำเร็จ: %s", exc)
        raise HTTPException(
            status_code=503, detail="ตัวช่วยตรวจ JD ไม่พร้อมใช้งานชั่วคราว"
        ) from exc


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str) -> JobOut:
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT {_JOB_COLS} FROM jobs WHERE id = %s", (job_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบตำแหน่งงานนี้")
    return JobOut(**row)


@router.patch("/{job_id}", response_model=JobOut)
def update_job_status(job_id: str, payload: JobStatusUpdate) -> JobOut:
    """เปิด/ปิดรับสมัคร — ทางเลือกแทนการลบสำหรับงานที่รับพนักงานได้แล้ว.

    ข้อมูลผู้สมัคร คะแนน หลักฐานการส่งอีเมล และเวกเตอร์ยังอยู่ครบ; ผลของการปิดคือ
    อัปโหลดเรซูเม่เพิ่มไม่ได้ (candidates.upload_resumes ตอบ 409) เท่านั้น
    """
    with get_conn() as conn:
        row = conn.execute(
            f"""
            UPDATE jobs
               SET status = %s,
                   closed_at = CASE WHEN %s = 'closed' THEN now() ELSE NULL END
             WHERE id = %s
            RETURNING {_JOB_COLS}
            """,
            (payload.status, payload.status, job_id),
        ).fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบตำแหน่งงานนี้")
    return JobOut(**row)


def _deletion_blocker(
    sent_count: int, active_count: int, employee_count: int = 0
) -> str | None:
    """เหตุผลที่ลบถาวรไม่ได้ (None = ลบได้) — แยกเป็นฟังก์ชันบริสุทธิ์เพื่อทดสอบได้.

    ลำดับความสำคัญ: พนักงานที่รับเข้าแล้วและอีเมลที่ส่งออกไปแล้วเป็นเหตุถาวร (ลองใหม่ก็ไม่หาย)
    มาก่อน ส่วน "กำลังประมวลผล" เป็นเหตุชั่วคราวที่ผู้ใช้แก้ได้ด้วยการรอ
    """
    if employee_count > 0:
        return (
            f"ตำแหน่งงานนี้มีผู้ถูกรับเข้าเป็นพนักงานแล้ว {employee_count} คน จึงลบถาวรไม่ได้ "
            "— ใช้ปิดรับสมัครแทนเพื่อเก็บทะเบียนพนักงานไว้"
        )
    if sent_count > 0:
        return (
            f"ตำแหน่งงานนี้ส่งอีเมลออกไปแล้ว {sent_count} ฉบับ จึงลบถาวรไม่ได้ "
            "— ใช้ปิดรับสมัครแทนเพื่อเก็บหลักฐานไว้"
        )
    if active_count > 0:
        return f"ระบบกำลังประมวลผลผู้สมัคร {active_count} คนอยู่ กรุณาลองอีกครั้งเมื่อเสร็จ"
    return None


@router.delete("/{job_id}", response_model=JobDeleteOut)
def delete_job(job_id: str) -> JobDeleteOut:
    """ลบตำแหน่งงานถาวร — สำหรับงานที่สร้างผิดเท่านั้น.

    FK เป็น ON DELETE CASCADE ทั้งสาย (candidates → evaluations / hr_decisions /
    resume_embeddings) แถว checkpoint ของ LangGraph ไม่มี FK จึงต้องเก็บ candidate_id
    ไว้ก่อนลบ แล้วค่อยเรียก delete_thread ตามหลัง
    """
    with get_conn() as conn:
        if conn.execute("SELECT id FROM jobs WHERE id = %s", (job_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="ไม่พบตำแหน่งงานนี้")
        rows = conn.execute(
            """
            SELECT c.id, (e.email_sent_at IS NOT NULL) AS sent,
                   (emp.id IS NOT NULL) AS is_employee
              FROM candidates c
              LEFT JOIN evaluations e ON e.candidate_id = c.id
              LEFT JOIN employees emp ON emp.candidate_id = c.id
             WHERE c.job_id = %s
            """,
            (job_id,),
        ).fetchall()

    candidate_ids = [str(r["id"]) for r in rows]
    sent_count = sum(1 for r in rows if r["sent"])
    employee_count = sum(1 for r in rows if r["is_employee"])
    active_count = len(set(candidate_ids) & active_candidates())
    blocker = _deletion_blocker(sent_count, active_count, employee_count)
    if blocker:
        raise HTTPException(status_code=409, detail=blocker)

    with get_conn() as conn:
        conn.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
        conn.commit()

    # ล้าง checkpoint หลัง commit เสมอ: ถ้าทำก่อนแล้ว DELETE ล้มเหลว จะพัง HITL ของงานที่ยังอยู่
    # ส่วนถ้าขั้นนี้ล้มเหลว ก็เหลือแค่ orphan ที่ไม่มีใครอ้างถึงแล้ว
    deleted_threads = 0
    for cid in candidate_ids:
        try:
            get_checkpointer().delete_thread(cid)
            deleted_threads += 1
        except Exception as exc:  # noqa: BLE001 — orphan ไม่กระทบการทำงาน
            log.warning("ลบ checkpoint ของผู้สมัคร %s ไม่สำเร็จ: %s", cid, exc)

    log.info(
        "ลบตำแหน่งงาน %s (ผู้สมัคร %d คน, checkpoint %d thread)",
        job_id, len(candidate_ids), deleted_threads,
    )
    return JobDeleteOut(
        id=job_id,
        deleted_candidates=len(candidate_ids),
        deleted_threads=deleted_threads,
    )
