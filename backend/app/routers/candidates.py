"""เราเตอร์ผู้สมัคร: อัปโหลด resume (async), รายชื่อ, และรายละเอียด."""
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile

from app.agents.runner import (
    active_candidates,
    get_graph_status,
    process_candidate,
    release_candidate,
    reserve_candidates,
)
from app.auth import get_current_user
from app.database import get_checkpointer, get_conn
from app.schemas import (
    CandidateDeleteOut,
    CandidateDetail,
    CandidateSearchHit,
    CandidateSummary,
    ResumeUploadAccepted,
)
from app.utils.pdf_extractor import extract_text_from_pdf
from app.vectors import search as vector_search

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1", tags=["candidates"], dependencies=[Depends(get_current_user)]
)

# จำกัดการอัปโหลดกัน DoS — ไฟล์ใหญ่/เยอะเกินจะกิน RAM (อ่านทั้งไฟล์เข้าหน่วยความจำ)
# และ pdfplumber แกะ PDF ที่ออกแบบมาให้หนัก (decompression bomb) ได้ ปรับผ่าน env
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
MAX_FILES = int(os.getenv("MAX_FILES", "20"))
_MAX_BYTES = MAX_UPLOAD_MB * 1024 * 1024
_PDF_MAGIC = b"%PDF-"  # PDF จริงต้องขึ้นต้นด้วยไบต์ชุดนี้ ไม่เชื่อแค่ชื่อไฟล์ .pdf

# ช่วงผ่อนผันก่อนจะบอกว่าผู้สมัคร "ค้าง" — กันแค่ช่วงสั้น ๆ ระหว่างที่แถวถูก INSERT แล้ว
# แต่ background task ยังไม่ทันจอง (คนที่รอคิวถูกจองไว้ตั้งแต่ต้น batch แล้ว)
_STALLED_AFTER_SEC = int(os.getenv("STALLED_AFTER_SEC", "90"))


def _is_stalled(candidate_id, has_eval: bool, created_at: datetime, active: frozenset[str]) -> bool:
    """ผู้สมัครที่ไม่มีใครประมวลผลให้แล้ว และจะไม่มีวันเสร็จเองถ้าไม่สั่งใหม่.

    BackgroundTasks อยู่ในโปรเซส — container รีสตาร์ต/hot-reload เมื่อไร งานที่ค้างหายทันที
    ไม่มีกลไก resume อัตโนมัติ แถวผู้สมัครจึงค้างเป็น "กำลังวิเคราะห์…" ตลอดกาลถ้าไม่ตรวจ
    """
    if has_eval or str(candidate_id) in active:
        return False
    return datetime.now(timezone.utc) - created_at > timedelta(seconds=_STALLED_AFTER_SEC)


def _run_graph_for_job(job_id: str, candidate_ids: list[str]) -> None:
    """Background task: รันกราฟทีละผู้สมัคร (thread_id = candidate_id) แล้วเขียนผลลง DB.

    การไหล: jd_analyzer(ข้าม, ใช้ criteria เดิม) -> resume_parser -> matcher
            -> bias_auditor -> route -> (auto: interview_planner+drafter | รอ HR | reject).
    """
    # จองทั้ง batch ทันที ไม่ใช่ทีละคนตอนถึงคิว — คนที่รอคิวต้องนับว่า "กำลังทำงาน" ด้วย
    reserve_candidates(candidate_ids)
    try:
        with get_conn() as conn:
            job = conn.execute(
                "SELECT raw_text, parsed_criteria FROM jobs WHERE id = %s", (job_id,)
            ).fetchone()
        if job is None:
            log.error("ไม่พบงาน %s ยกเลิกการประมวลผลผู้สมัคร", job_id)
            return

        for cid in candidate_ids:
            with get_conn() as conn:
                cand = conn.execute(
                    "SELECT raw_resume_text FROM candidates WHERE id = %s", (cid,)
                ).fetchone()
            if cand is None:
                continue
            try:
                process_candidate(
                    job_id=job_id,
                    candidate_id=cid,
                    raw_jd=job["raw_text"],
                    analyzed_jd=job["parsed_criteria"],
                    resume_text=cand["raw_resume_text"] or "",
                )
            except Exception as exc:  # noqa: BLE001 — ผู้สมัครรายอื่นต้องไปต่อได้
                log.exception("ประมวลผลผู้สมัคร %s ล้มเหลว: %s", cid, exc)
    finally:
        # ปลดจองทุกคนเสมอ รวมถึงกรณี job หายกลางทาง ไม่งั้นจะค้างในทะเบียนตลอดอายุโปรเซส
        for cid in candidate_ids:
            release_candidate(cid)


@router.post(
    "/jobs/{job_id}/resumes",
    response_model=ResumeUploadAccepted,
    status_code=202,
)
async def upload_resumes(
    job_id: str,
    files: list[UploadFile],
    background_tasks: BackgroundTasks,
) -> ResumeUploadAccepted:
    """อัปโหลด PDF หลายไฟล์: สกัดข้อความ, บันทึกแถวผู้สมัคร, แล้วรันกราฟเบื้องหลัง."""
    with get_conn() as conn:
        job = conn.execute(
            "SELECT id, status FROM jobs WHERE id = %s", (job_id,)
        ).fetchone()
    if job is None:
        raise HTTPException(status_code=404, detail="ไม่พบตำแหน่งงานนี้")
    # UI ซ่อนปุ่มอัปโหลดไว้แล้ว แต่ต้องกันที่ API ด้วยเพราะยิงตรงได้
    if job["status"] == "closed":
        raise HTTPException(
            status_code=409,
            detail="ตำแหน่งงานนี้ปิดรับสมัครแล้ว — เปิดรับสมัครอีกครั้งก่อนอัปโหลด",
        )

    if len(files) > MAX_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"อัปโหลดได้สูงสุด {MAX_FILES} ไฟล์ต่อครั้ง (ส่งมา {len(files)})",
        )

    candidate_ids: list[UUID] = []
    with get_conn() as conn:
        for file in files:
            if not (file.filename or "").lower().endswith(".pdf"):
                raise HTTPException(
                    status_code=400,
                    detail=f"รองรับเฉพาะไฟล์ PDF: {file.filename}",
                )
            content = await file.read()
            if len(content) > _MAX_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"ไฟล์ {file.filename} ใหญ่เกิน {MAX_UPLOAD_MB}MB",
                )
            # ตรวจ magic bytes — ไม่เชื่อแค่นามสกุล .pdf (เปลี่ยนชื่อไฟล์อะไรก็ได้)
            if not content.startswith(_PDF_MAGIC):
                raise HTTPException(
                    status_code=400,
                    detail=f"ไฟล์ {file.filename} ไม่ใช่ PDF ที่ถูกต้อง",
                )
            # แกะข้อความแบบ graceful — PDF เสีย/แกะไม่ได้ ไม่ควรล้มทั้ง batch
            try:
                raw = extract_text_from_pdf(content)
            except Exception as exc:  # noqa: BLE001
                log.warning("แกะข้อความจาก %s ไม่สำเร็จ: %s", file.filename, exc)
                raw = ""
            # full_name ชั่วคราวจากชื่อไฟล์ — resume_parser จะอัปเดตเป็นชื่อจริงภายหลัง
            placeholder_name = PurePath(file.filename).stem[:255]
            row = conn.execute(
                """
                INSERT INTO candidates (job_id, full_name, raw_resume_text)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (job_id, placeholder_name, raw),
            ).fetchone()
            candidate_ids.append(row["id"])
        conn.commit()

    # เตะกราฟให้ทำงานเบื้องหลังแล้วตอบกลับทันที (frontend จะ poll เอง)
    background_tasks.add_task(
        _run_graph_for_job, job_id, [str(c) for c in candidate_ids]
    )
    return ResumeUploadAccepted(
        job_id=UUID(job_id), accepted=len(candidate_ids), candidate_ids=candidate_ids
    )


@router.get("/jobs/{job_id}/candidates", response_model=list[CandidateSummary])
def list_candidates(job_id: str) -> list[CandidateSummary]:
    """รายชื่อผู้สมัครทั้งหมดของตำแหน่งนี้ เรียงตาม fit_score (มาก -> น้อย)."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.job_id, c.full_name, c.email,
                   e.fit_score, e.audit_status, e.gap_analysis, c.created_at,
                   (e.id IS NOT NULL) AS has_eval
            FROM candidates c
            LEFT JOIN evaluations e ON e.candidate_id = c.id
            WHERE c.job_id = %s
            ORDER BY e.fit_score DESC NULLS LAST, c.created_at ASC
            """,
            (job_id,),
        ).fetchall()
    active = active_candidates()
    return [
        CandidateSummary(
            **{k: v for k, v in r.items() if k != "has_eval"},
            stalled=_is_stalled(r["id"], r["has_eval"], r["created_at"], active),
        )
        for r in rows
    ]


def _candidate_deletion_blocker(
    email_sent: bool, is_active: bool, is_employee: bool = False
) -> str | None:
    """เหตุผลที่ลบผู้สมัครไม่ได้ (None = ลบได้) — ฟังก์ชันบริสุทธิ์เพื่อทดสอบได้.

    ใช้กฎเดียวกับการลบตำแหน่งงาน (jobs.py::_deletion_blocker): อีเมลที่ส่งออกไปแล้ว
    เป็นเหตุถาวรและมาก่อน เพราะลบแถวไม่ได้ทำให้อีเมลที่ถึงผู้สมัครแล้วหายไป
    ผู้ที่ถูกรับเข้าเป็นพนักงานแล้วก็เป็นเหตุถาวรเช่นกัน (ระเบียนพนักงานต้องคงอยู่)
    """
    if is_employee:
        return "ผู้สมัครรายนี้ถูกรับเข้าเป็นพนักงานแล้ว จึงลบไม่ได้ (ต้องเก็บทะเบียนพนักงานไว้)"
    if email_sent:
        return "เคยส่งอีเมลถึงผู้สมัครรายนี้แล้ว จึงลบไม่ได้ (ต้องเก็บไว้เป็นหลักฐาน)"
    if is_active:
        return "กำลังวิเคราะห์ผู้สมัครรายนี้อยู่ กรุณาลองอีกครั้งเมื่อเสร็จ"
    return None


@router.delete("/candidates/{candidate_id}", response_model=CandidateDeleteOut)
def delete_candidate(candidate_id: str) -> CandidateDeleteOut:
    """ลบผู้สมัครถาวร — สำหรับกรณีอัปโหลดผิดไฟล์หรืออัปซ้ำ.

    ขอบเขตแคบกว่าการลบตำแหน่งงานมาก: cascade กระทบเฉพาะ evaluations / hr_decisions /
    resume_embeddings ของคนคนเดียว ไม่แตะงานหรือผู้สมัครรายอื่น
    checkpoint ไม่มี FK เหมือนเดิม จึงต้องเรียก delete_thread เอง **หลัง** commit
    """
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT (e.email_sent_at IS NOT NULL) AS email_sent,
                   (emp.id IS NOT NULL) AS is_employee
              FROM candidates c
              LEFT JOIN evaluations e ON e.candidate_id = c.id
              LEFT JOIN employees emp ON emp.candidate_id = c.id
             WHERE c.id = %s
            """,
            (candidate_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบผู้สมัครนี้")

    blocker = _candidate_deletion_blocker(
        email_sent=bool(row["email_sent"]),
        is_active=str(candidate_id) in active_candidates(),
        is_employee=bool(row["is_employee"]),
    )
    if blocker:
        raise HTTPException(status_code=409, detail=blocker)

    with get_conn() as conn:
        conn.execute("DELETE FROM candidates WHERE id = %s", (candidate_id,))
        conn.commit()

    deleted_thread = False
    try:
        get_checkpointer().delete_thread(str(candidate_id))
        deleted_thread = True
    except Exception as exc:  # noqa: BLE001 — orphan ไม่กระทบการทำงาน แค่กินที่
        log.warning("ลบ checkpoint ของผู้สมัคร %s ไม่สำเร็จ: %s", candidate_id, exc)

    log.info("ลบผู้สมัคร %s (checkpoint ลบแล้ว=%s)", candidate_id, deleted_thread)
    return CandidateDeleteOut(id=candidate_id, deleted_thread=deleted_thread)


@router.post("/candidates/{candidate_id}/reprocess", status_code=202)
def reprocess_candidate(candidate_id: str, background_tasks: BackgroundTasks) -> dict:
    """สั่งวิเคราะห์ผู้สมัครที่ค้างใหม่ — ใช้ `raw_resume_text` ใน DB ไม่ต้องอัปโหลด PDF ซ้ำ.

    เจตนาแคบ: กู้เคสที่กราฟตายกลางทาง (โควตา LLM หมด / container รีสตาร์ต) เท่านั้น
    ถ้ามีผลวิเคราะห์แล้วจะปฏิเสธ เพราะการรันซ้ำจะเสียโควตาฟรี ๆ และอาจทับผล HITL ที่ HR ตัดสินไปแล้ว

    ต้นทุนโควตา: **วัดจริงได้ 3 chat call ต่อคน** (resume_parser + bias_auditor + drafter;
    jd_analyzer ถูกข้ามเพราะส่ง analyzed_jd เข้าไปแล้ว, matcher ไม่ใช้ LLM) — checkpoint เดิม
    ไม่ได้ช่วยประหยัดในทางปฏิบัติ เพราะเคสที่ค้างมักตายตั้งแต่โหนดแรก ๆ
    """
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT c.raw_resume_text, c.job_id, j.raw_text, j.parsed_criteria,
                   (e.id IS NOT NULL) AS has_eval
              FROM candidates c
              JOIN jobs j ON j.id = c.job_id
              LEFT JOIN evaluations e ON e.candidate_id = c.id
             WHERE c.id = %s
            """,
            (candidate_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบผู้สมัครนี้")
    if row["has_eval"]:
        raise HTTPException(status_code=409, detail="ผู้สมัครรายนี้วิเคราะห์เสร็จแล้ว")
    if str(candidate_id) in active_candidates():
        raise HTTPException(status_code=409, detail="กำลังวิเคราะห์อยู่แล้ว กรุณารอสักครู่")
    if not (row["raw_resume_text"] or "").strip():
        raise HTTPException(
            status_code=422,
            detail="ไม่มีข้อความเรซูเม่ในระบบ (สกัดจาก PDF ไม่ได้) — ต้องอัปโหลดไฟล์ใหม่",
        )

    reserve_candidates([candidate_id])  # จองทันทีในเธรด request กันกดรัว ๆ ซ้อนกัน
    background_tasks.add_task(
        _reprocess_one,
        job_id=str(row["job_id"]),
        candidate_id=candidate_id,
        raw_jd=row["raw_text"],
        analyzed_jd=row["parsed_criteria"],
        resume_text=row["raw_resume_text"],
    )
    return {"candidate_id": candidate_id, "message": "เริ่มวิเคราะห์ใหม่แล้ว — โปรด poll รายชื่อผู้สมัคร"}


def _reprocess_one(
    job_id: str, candidate_id: str, raw_jd: str, analyzed_jd: dict | None, resume_text: str
) -> None:
    """Background task ของ reprocess — ปลดจองเสมอแม้กราฟจะพังซ้ำ."""
    try:
        process_candidate(
            job_id=job_id,
            candidate_id=candidate_id,
            raw_jd=raw_jd,
            analyzed_jd=analyzed_jd,
            resume_text=resume_text,
        )
    except Exception as exc:  # noqa: BLE001 — ล้มซ้ำได้ (โควตายังหมดอยู่) แค่ต้องไม่ค้างในทะเบียน
        log.exception("วิเคราะห์ผู้สมัคร %s ใหม่ล้มเหลว: %s", candidate_id, exc)
    finally:
        release_candidate(candidate_id)


@router.get("/candidates/search", response_model=list[CandidateSearchHit])
def search_candidates(q: str, limit: int = 10) -> list[CandidateSearchHit]:
    """ค้นหาผู้สมัครเก่าด้วยความหมายของข้อความ (ไม่ใช่การจับคำ).

    ⚠️ ต้องประกาศ **ก่อน** /candidates/{candidate_id} ไม่งั้น FastAPI จะจับคู่เส้นทางนี้
    เป็น candidate_id = "search" แล้วตอบ 404
    """
    if not q.strip():
        raise HTTPException(status_code=400, detail="ต้องระบุคำค้นหา")
    try:
        hits = vector_search(q, limit=max(1, min(limit, 50)))
    except Exception as exc:  # noqa: BLE001 — โควตา embedding หมด/คีย์ผิด ไม่ควรเป็น 500 เปล่า ๆ
        log.exception("ค้นหาเชิงความหมายล้มเหลว: %s", exc)
        raise HTTPException(status_code=503, detail="ระบบค้นหาไม่พร้อมใช้งานชั่วคราว") from exc
    return [CandidateSearchHit(**h) for h in hits]


@router.get("/candidates/{candidate_id}", response_model=CandidateDetail)
def get_candidate(candidate_id: str) -> CandidateDetail:
    """รายงานรายบุคคล: ประวัติที่แกะแล้ว, Gap Analysis, และผลลัพธ์ของ AI."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT c.id, c.job_id, c.full_name, c.email,
                   c.raw_resume_text, c.parsed_resume, c.created_at,
                   e.fit_score, e.audit_status, e.audit_log, e.gap_analysis,
                   e.interview_plan, e.email_draft, e.email_sent_at, e.email_sent_to,
                   COALESCE(e.email_send_count, 0) AS email_send_count,
                   e.similar_candidates, (e.id IS NOT NULL) AS has_eval,
                   emp.id AS employee_id, hd.decision AS hr_decision
            FROM candidates c
            LEFT JOIN evaluations e ON e.candidate_id = c.id
            LEFT JOIN employees emp ON emp.candidate_id = c.id
            LEFT JOIN hr_decisions hd ON hd.candidate_id = c.id
            WHERE c.id = %s
            """,
            (candidate_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบผู้สมัครนี้")
    has_eval = row.pop("has_eval")
    return CandidateDetail(
        **row,
        graph_status=get_graph_status(candidate_id),
        stalled=_is_stalled(candidate_id, has_eval, row["created_at"], active_candidates()),
    )
