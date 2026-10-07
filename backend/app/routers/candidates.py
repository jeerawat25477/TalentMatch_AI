"""เราเตอร์ผู้สมัคร: อัปโหลด resume (async), รายชื่อ, และรายละเอียด."""
import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile

from app.bias_ack import bias_view
from app.agents.nodes.matcher import score_breakdown
from app.criteria_edit import needs_recheck
from app.agents.runner import active_candidates, get_graph_status, reserve_candidates
from app.auth import get_current_user
from app.database import get_checkpointer, get_conn
from app.hiring_board import board_stage
from app.job_queue import PENDING_STATUSES, enqueue, enqueue_many, pending_status
from app.resume_ingest import (
    MAX_FILES,
    MAX_UPLOAD_MB,
    Verdict,
    admit_resume,
    existing_hashes_for_job,
    is_duplicate_upload,
    is_unreadable_resume,
)
from app.schemas import (
    CandidateDeleteOut,
    CandidateDetail,
    CandidateSearchHit,
    CandidateSummary,
    PersonSearchHit,
    ResumeUploadAccepted,
)
from app.vectors import search as vector_search

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1", tags=["candidates"], dependencies=[Depends(get_current_user)]
)

# ด่านตรวจไฟล์ทั้งหมด (magic byte / ขนาด / ซ้ำ / อ่านไม่ออก / INSERT) ย้ายไปอยู่ที่
# app/resume_ingest.py แล้ว เพื่อให้ทางเข้าที่สอง (ปากทางอีเมล) ใช้กฎชุดเดียวกันเป๊ะ
# ชื่อเดิมที่ขึ้นต้นด้วย _ ยังคงไว้ให้เรียกในไฟล์นี้ได้เหมือนเดิม
_is_unreadable_resume = is_unreadable_resume
_is_duplicate_upload = is_duplicate_upload


# ช่วงผ่อนผันก่อนจะบอกว่าผู้สมัคร "ค้าง" — กันแค่ช่วงสั้น ๆ ระหว่างที่แถวถูก INSERT แล้ว
# แต่ background task ยังไม่ทันจอง (คนที่รอคิวถูกจองไว้ตั้งแต่ต้น batch แล้ว)
_STALLED_AFTER_SEC = int(os.getenv("STALLED_AFTER_SEC", "90"))


def _is_stalled(
    candidate_id,
    has_eval: bool,
    created_at: datetime,
    active: frozenset[str],
    queue_status: str | None = None,
) -> bool:
    """ผู้สมัครที่ไม่มีใครประมวลผลให้แล้ว และจะไม่มีวันเสร็จเองถ้าไม่สั่งใหม่.

    เดิมเป็นกรณีที่เกิดบ่อยมาก เพราะ BackgroundTasks อยู่ในโปรเซส (รีสตาร์ต = งานหาย)
    ตอนนี้งานอยู่ในตาราง processing_queue ที่ worker กู้ให้เองหลังรีสตาร์ต จึงเหลือแค่
    เศษของเก่าและเคสที่งานตกไปจริง ๆ (failed)

    **ต้องเช็คคิวก่อนเสมอ**: คนที่รอคิวอยู่ 20 นาที (หรือถูกพักเพราะโควตาถึงพรุ่งนี้)
    ยังมีคนดูแลอยู่ ถ้าตีเป็น "ค้าง" HR จะกด "วิเคราะห์ใหม่" ซ้ำแล้วเสียโควตาฟรี ๆ
    ทั้งที่งานเดิมกำลังจะได้รันอยู่แล้ว
    """
    if has_eval or str(candidate_id) in active:
        return False
    if queue_status in PENDING_STATUSES:
        return False
    return datetime.now(timezone.utc) - created_at > timedelta(seconds=_STALLED_AFTER_SEC)


def _effective_graph_status(
    raw_status: str, candidate_id, active: frozenset[str], queue_status: str | None
) -> str:
    """ทับ "interrupted" เป็น "processing" เมื่อมีคนดูแลงานนี้อยู่ — ฟังก์ชันบริสุทธิ์.

    checkpoint ถูกบันทึกทุกขั้น ระหว่างกราฟเดินหรือรอคิว มันจึงดูเหมือนค้างกลางทางชั่วขณะ
    ถ้าไม่ทับ ป้าย "หยุดกลางทาง" กับปุ่มทำต่อจะกะพริบขึ้นมาให้ HR กดซ้ำ ทั้งที่งานกำลังเดินอยู่
    """
    if raw_status == "interrupted" and (
        str(candidate_id) in active or queue_status in PENDING_STATUSES
    ):
        return "processing"
    return raw_status


@router.post(
    "/jobs/{job_id}/resumes",
    response_model=ResumeUploadAccepted,
    status_code=202,
)
async def upload_resumes(
    job_id: str,
    files: list[UploadFile],
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
    duplicate_files: list[str] = []
    unreadable_files: list[str] = []
    seen_in_batch: set[str] = set()
    with get_conn() as conn:
        existing_hashes = existing_hashes_for_job(conn, job_id)
        for file in files:
            if not (file.filename or "").lower().endswith(".pdf"):
                raise HTTPException(
                    status_code=400,
                    detail=f"รองรับเฉพาะไฟล์ PDF: {file.filename}",
                )
            content = await file.read()
            # ด่านจริงทั้งหมดอยู่ใน resume_ingest.admit_resume — ที่นี่แค่แปลงคำตัดสิน
            # เป็นภาษา HTTP · ปากทางอีเมลแปลงคำตัดสินชุดเดียวกันเป็น log แทน
            verdict, candidate_id = admit_resume(
                conn, job_id, file.filename or "", content, seen_in_batch, existing_hashes
            )
            if verdict is Verdict.TOO_LARGE:
                raise HTTPException(
                    status_code=413,
                    detail=f"ไฟล์ {file.filename} ใหญ่เกิน {MAX_UPLOAD_MB}MB",
                )
            if verdict is Verdict.NOT_PDF:
                raise HTTPException(
                    status_code=400,
                    detail=f"ไฟล์ {file.filename} ไม่ใช่ PDF ที่ถูกต้อง",
                )
            if verdict is Verdict.DUPLICATE:
                duplicate_files.append(file.filename or "")
            elif verdict is Verdict.UNREADABLE:
                unreadable_files.append(file.filename or "")
            else:
                candidate_ids.append(candidate_id)
        conn.commit()

    # เข้าคิวแล้วตอบกลับทันที (frontend poll เหมือนเดิม ไม่ต้องแก้อะไร)
    # ต่างจากเดิมตรงที่งานอยู่ใน DB ไม่ใช่ในหน่วยความจำของโปรเซส — รีสตาร์ตแล้วไม่หาย
    # และ worker จะทยอยรันตามโควตาที่เหลือ ไม่ยิงเข้ากราฟทั้ง 20 คนพร้อมกันจนชน RPD
    if candidate_ids:
        ids = [str(c) for c in candidate_ids]
        # ยังจองทั้ง batch ไว้เหมือนเดิม: ทะเบียนในโปรเซสตอบคำถาม "ตอนนี้ใครกำลังรัน"
        # (กันลบ/กันกดซ้ำ) ส่วนคิวตอบ "ยังมีอะไรค้างต้องทำ" — คนละคำถาม ต้องมีคู่กัน
        reserve_candidates(ids)
        enqueue_many([(cid, job_id, "process", None) for cid in ids])
    return ResumeUploadAccepted(
        job_id=UUID(job_id),
        accepted=len(candidate_ids),
        candidate_ids=candidate_ids,
        skipped=len(duplicate_files) + len(unreadable_files),
        duplicate_files=duplicate_files,
        unreadable_files=unreadable_files,
    )


@router.get("/jobs/{job_id}/candidates", response_model=list[CandidateSummary])
def list_candidates(job_id: str) -> list[CandidateSummary]:
    """รายชื่อผู้สมัครทั้งหมดของตำแหน่งนี้ เรียงตาม fit_score (มาก -> น้อย)."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.job_id, c.full_name, c.email,
                   e.fit_score, e.audit_status, e.gap_analysis, c.created_at,
                   hd.decision AS hr_decision, hd.updated_at AS hr_decided_at,
                   e.rescored_from, e.rescored_at,
                   (e.id IS NOT NULL) AS has_eval,
                   q.status AS queue_status
            FROM candidates c
            LEFT JOIN evaluations e ON e.candidate_id = c.id
            LEFT JOIN hr_decisions hd ON hd.candidate_id = c.id
            -- สถานะคิวที่ยังทำงานอยู่ของแต่ละคน (LATERAL = query เดียวทั้งหน้า
            -- ไม่ใช่ยิงต่อแถว — หน้านี้ poll ทุก 4 วินาที)
            LEFT JOIN LATERAL (
                SELECT status FROM processing_queue pq
                 WHERE pq.candidate_id = c.id AND pq.status = ANY(%s)
                 ORDER BY pq.created_at LIMIT 1
            ) q ON TRUE
            WHERE c.job_id = %s
            ORDER BY e.fit_score DESC NULLS LAST, c.created_at ASC
            """,
            (list(PENDING_STATUSES), job_id),
        ).fetchall()
    active = active_candidates()
    return [
        CandidateSummary(
            **{k: v for k, v in r.items() if k not in ("has_eval", "rescored_at", "hr_decided_at")},
            needs_recheck=needs_recheck(
                r["rescored_at"], r["rescored_from"], r["fit_score"], r["hr_decided_at"]
            ),
            stalled=_is_stalled(
                r["id"], r["has_eval"], r["created_at"], active, r["queue_status"]
            ),
            # อ่าน checkpoint เฉพาะคนที่วิเคราะห์เสร็จแล้ว — คนที่ยังไม่มีผลประเมินเป็น
            # processing/stalled อยู่แล้ว ไม่ต้องเสีย query (หน้านี้ poll ทุก 4 วิ)
            graph_status=(
                _effective_graph_status(
                    get_graph_status(str(r["id"]), r["hr_decision"], r["fit_score"]),
                    r["id"], active, r["queue_status"],
                )
                if r["has_eval"]
                else "processing"
            ),
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
def reprocess_candidate(candidate_id: str) -> dict:
    """สั่งวิเคราะห์ผู้สมัครที่ค้างใหม่ — ใช้ `raw_resume_text` ใน DB ไม่ต้องอัปโหลด PDF ซ้ำ.

    เจตนาแคบ: กู้เคสที่กราฟตายกลางทาง (โควตา LLM หมด / container รีสตาร์ต) เท่านั้น
    ถ้ามีผลวิเคราะห์แล้วจะปฏิเสธ เพราะการรันซ้ำจะเสียโควตาฟรี ๆ และอาจทับผล HITL ที่ HR ตัดสินไปแล้ว

    ต้นทุนโควตา: **วัดจริง 4-5 chat call ต่อคน** (resume_parser 2 ครั้ง คือโปรไฟล์ +
    หาหลักฐานทักษะ, bias_auditor, email_drafter และ interview_planner อีกครั้งถ้าคะแนน
    สูงจน auto-advance; jd_analyzer ถูกข้ามเพราะส่ง analyzed_jd เข้าไปแล้ว, matcher
    ไม่ใช้ LLM) — checkpoint เดิมไม่ได้ช่วยประหยัดในทางปฏิบัติ เพราะเคสที่ค้างมักตาย
    ตั้งแต่โหนดแรก ๆ · ตัวเลขนี้อยู่ที่ job_queue.COST_BY_KIND เพื่อให้คิวคุมโควตาได้
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
    # ทะเบียนในโปรเซสหายไปตอนรีสตาร์ต แต่แถวในคิวไม่หาย — ถ้าไม่เช็คตรงนี้ด้วย
    # HR จะสั่งซ้ำเข้าคิวได้หลังรีสตาร์ต แล้วผู้สมัครคนเดียวจะถูกรันสองรอบ (เสียโควตา)
    if pending_status(candidate_id):
        raise HTTPException(status_code=409, detail="งานของผู้สมัครรายนี้อยู่ในคิวแล้ว กรุณารอสักครู่")
    # ใช้เกณฑ์เดียวกับด่านอัปโหลด — ไม่งั้นจะมีเคส "อัปโหลดไม่ผ่าน แต่ reprocess ปล่อยผ่าน"
    if _is_unreadable_resume(row["raw_resume_text"]):
        raise HTTPException(
            status_code=422,
            detail="ไม่มีข้อความเรซูเม่ในระบบ (สกัดจาก PDF ไม่ได้) — ต้องอัปโหลดไฟล์ใหม่",
        )

    reserve_candidates([candidate_id])  # จองทันทีในเธรด request กันกดรัว ๆ ซ้อนกัน
    enqueue(candidate_id, str(row["job_id"]), "reprocess")
    return {"candidate_id": candidate_id, "message": "เข้าคิววิเคราะห์ใหม่แล้ว — โปรด poll รายชื่อผู้สมัคร"}


@router.post("/candidates/{candidate_id}/resume", status_code=202)
def resume_candidate(candidate_id: str) -> dict:
    """สั่งกราฟที่หยุดกลางทางให้เดินต่อจากจุดที่ค้าง — ไม่รันใหม่ตั้งแต่ต้น.

    คู่กับ reprocess แต่คนละเคส: reprocess กู้คนที่ **ยังไม่มีผลวิเคราะห์เลย** ส่วนตัวนี้กู้คน
    ที่คัดกรองเสร็จแล้วแต่ขั้นหลังจากนั้นไม่จบ เช่น HR อนุมัติแล้ว planner สร้างคำถามเสร็จ
    แต่ drafter ล้มเพราะโควตา · งานที่คิวลองใหม่เองได้อยู่แล้วไม่ต้องใช้ปุ่มนี้ มันมีไว้สำหรับ
    งานที่คิวยอมแพ้ (failed) และของค้างจากยุคก่อนมีคิว

    ไม่มี kind ใหม่: มีคำตัดสินของ HR → resume_after_decision (update_state แล้วเดินต่อ
    จากโหนดที่ค้าง) · ไม่มี → process ซึ่งเดินต่อจาก checkpoint ผ่าน runner._resume_point
    ต้นทุนจริงคือเฉพาะโหนดที่ยังไม่ได้รัน เช่นค้างที่ drafter = 1 call
    """
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT c.job_id, e.fit_score, hd.decision, hd.notes
              FROM candidates c
              LEFT JOIN evaluations e ON e.candidate_id = c.id
              LEFT JOIN hr_decisions hd ON hd.candidate_id = c.id
             WHERE c.id = %s
            """,
            (candidate_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบผู้สมัครนี้")
    if str(candidate_id) in active_candidates():
        raise HTTPException(status_code=409, detail="กำลังประมวลผลอยู่แล้ว กรุณารอสักครู่")
    if pending_status(candidate_id):
        raise HTTPException(status_code=409, detail="งานของผู้สมัครรายนี้อยู่ในคิวแล้ว กรุณารอสักครู่")
    status = get_graph_status(candidate_id, row["decision"], row["fit_score"])
    if status != "interrupted":
        raise HTTPException(
            status_code=409,
            detail="ผู้สมัครรายนี้ไม่ได้หยุดกลางทาง — ไม่มีขั้นที่ต้องทำต่อ",
        )

    reserve_candidates([candidate_id])
    if row["decision"] in ("approved", "rejected"):
        enqueue(
            candidate_id, str(row["job_id"]), "resume_after_decision",
            {"decision": row["decision"], "notes": row["notes"]},
        )
    else:
        enqueue(candidate_id, str(row["job_id"]), "process")
    log.info("สั่งทำต่อผู้สมัคร %s (คำตัดสิน=%s)", candidate_id, row["decision"])
    return {"candidate_id": candidate_id, "message": "เข้าคิวทำต่อจากจุดที่ค้างแล้ว"}


def same_person(current: dict, other: dict) -> str | None:
    """สองแถวนี้เป็นคนเดียวกันไหม — ฟังก์ชันบริสุทธิ์ ทดสอบได้ไม่ต้องมี DB.

    รับ dict ที่มี `sha` (resume_sha256), `text_md5` (md5 ของข้อความเรซูเม่), `email`
    - "same_file"  = ไฟล์เดียวกัน: sha ตรง หรือข้อความตรงทุกตัวอักษร (แถวเก่าก่อนมี sha เป็น NULL)
    - "same_email" = คนละไฟล์แต่อีเมลในเรซูเม่ตรง (เช่น เรซูเม่ไทย/อังกฤษของคนเดียวกัน)
      อีเมลมาจาก PDF ที่ใครจะพิมพ์อะไรก็ได้ หน้าเว็บจึงเขียนว่า "น่าจะ" — เป็นข้อมูลประกอบเท่านั้น

    ทำไมต้องมี: % ความคล้ายเทียบ "รายการทักษะ" กับ "เรซูเม่ทั้งฉบับ" ไฟล์เดียวกันเป๊ะยังได้แค่ ~78%
    HR จึงดูจากตัวเลขไม่ออกว่าแถวนั้นคือคนเดิมที่เคยสมัครมาแล้ว
    """
    if current.get("sha") and current.get("sha") == other.get("sha"):
        return "same_file"
    if current.get("text_md5") and current.get("text_md5") == other.get("text_md5"):
        return "same_file"
    a = (current.get("email") or "").strip().lower()
    if a and a == (other.get("email") or "").strip().lower():
        return "same_email"
    return None


def _mark_same_person(current_id: str, hits: list[dict]) -> list[dict]:
    """เติม `same_person` ให้ทุกแถวใน hits เทียบกับ current_id — query เดียว ไม่เรียก AI.

    คำนวณตอนเปิดหน้า ไม่ได้เก็บตอนวิเคราะห์ ผู้สมัครเดิมทุกคนจึงได้ป้ายโดยไม่ต้องรันใหม่
    """
    if not hits:
        return hits
    ids = [str(current_id)] + [str(h["id"]) for h in hits if h.get("id")]
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id::text AS id, resume_sha256 AS sha,
                      md5(NULLIF(raw_resume_text, '')) AS text_md5, email
                 FROM candidates WHERE id::text = ANY(%s)""",
            (ids,),
        ).fetchall()
    by_id = {r["id"]: r for r in rows}
    current = by_id.get(str(current_id)) or {}
    return [
        {**h, "same_person": same_person(current, by_id.get(str(h.get("id"))) or {})}
        for h in hits
    ]


def group_people(rows: list[dict]) -> list[dict]:
    """รวมใบสมัครของคนเดียวกันเป็นหนึ่งคน — ฟังก์ชันบริสุทธิ์ ทดสอบได้ไม่ต้องมี DB.

    แต่ละแถว = ใบสมัครหนึ่งใบ (id, job_id, job_title, fit_score, created_at, full_name, email,
    sha, text_md5, has_parsed, distance ซึ่งเป็น None ได้) · ใช้หลัก same_person เดียวกับป้าย
    และต่อกันเป็นทอด: A ไฟล์ตรง B, B อีเมลตรง C → คนเดียวกันทั้งสาม
    คืนเรียงตาม distance ที่ดีที่สุดของแต่ละคน ใบสมัครในแต่ละคนเรียงจากล่าสุด
    """
    parent = list(range(len(rows)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if same_person(rows[i], rows[j]):
                parent[root(i)] = root(j)

    groups: dict[int, list[dict]] = {}
    for i, r in enumerate(rows):
        groups.setdefault(root(i), []).append(r)

    people = []
    for apps in groups.values():
        apps = sorted(apps, key=lambda r: r["created_at"], reverse=True)
        distances = [r["distance"] for r in apps if r.get("distance") is not None]
        if not distances:
            continue
        # ชื่อ/อีเมลจากใบล่าสุดที่ AI อ่านชื่อได้แล้ว (แถวที่ยังไม่วิเคราะห์ใช้ชื่อไฟล์แทนชื่อคน)
        face = next((r for r in apps if r.get("has_parsed")), apps[0])
        files = {r.get("sha") or r.get("text_md5") or r["id"] for r in apps}
        merged_by = "same_email" if len(files) > 1 else ("same_file" if len(apps) > 1 else None)
        people.append({
            "full_name": face.get("full_name") or "—",
            "email": face.get("email"),
            "distance": min(distances),
            "merged_by": merged_by,
            "file_count": len(files),
            "applications": [
                {"candidate_id": r["id"], "job_id": r["job_id"], "job_title": r.get("job_title"),
                 "fit_score": r.get("fit_score"), "applied_at": r["created_at"]}
                for r in apps
            ],
        })
    return sorted(people, key=lambda p: p["distance"])


@router.get("/candidates/search/people", response_model=list[PersonSearchHit])
def search_people(q: str, limit: int = 10) -> list[PersonSearchHit]:
    """ค้นหาเชิงความหมายแบบรวมคนเดียวกันเป็นแถวเดียว — ใช้ในหน้า "ค้นหาผู้สมัคร".

    ค้นเวกเตอร์เผื่อไว้ 30 ไฟล์ (คนเดียวมีหลายไฟล์จะกินที่) แล้วดึงใบสมัครทั้งหมดของคนเหล่านั้น
    เพราะใบสมัครที่ใช้ไฟล์ซ้ำถูกยุบไปตั้งแต่ขั้นค้นเวกเตอร์ (DISTINCT ON เนื้อหา)
    """
    if not q.strip():
        raise HTTPException(status_code=400, detail="ต้องระบุคำค้นหา")
    try:
        hits = vector_search(q, limit=30)
    except Exception as exc:  # noqa: BLE001 — แบบเดียวกับ /candidates/search
        log.exception("ค้นหาเชิงความหมายล้มเหลว: %s", exc)
        raise HTTPException(status_code=503, detail="ระบบค้นหาไม่พร้อมใช้งานชั่วคราว") from exc
    if not hits:
        return []
    hit_dist = {str(h["id"]): h["distance"] for h in hits}
    with get_conn() as conn:
        rows = conn.execute(
            """WITH seed AS (
                   SELECT resume_sha256 AS sha, md5(NULLIF(raw_resume_text, '')) AS tm,
                          NULLIF(lower(trim(email)), '') AS em
                     FROM candidates WHERE id::text = ANY(%s)
               )
               SELECT c.id::text AS id, c.job_id::text AS job_id, j.title AS job_title,
                      e.fit_score, c.created_at, c.full_name, c.email,
                      c.resume_sha256 AS sha, md5(NULLIF(c.raw_resume_text, '')) AS text_md5,
                      (c.parsed_resume IS NOT NULL) AS has_parsed
                 FROM candidates c
                 JOIN jobs j ON j.id = c.job_id
                 LEFT JOIN evaluations e ON e.candidate_id = c.id
                WHERE c.resume_sha256 IN (SELECT sha FROM seed WHERE sha IS NOT NULL)
                   OR md5(NULLIF(c.raw_resume_text, '')) IN (SELECT tm FROM seed WHERE tm IS NOT NULL)
                   OR NULLIF(lower(trim(c.email)), '') IN (SELECT em FROM seed WHERE em IS NOT NULL)""",
            (list(hit_dist),),
        ).fetchall()
    # ใบสมัครที่ไฟล์ซ้ำกับแถวที่ค้นเจอ ได้ระยะเดียวกัน (เวกเตอร์มาจากข้อความเดียวกัน)
    rows = [dict(r) for r in rows]
    dist_by_text = {
        r["text_md5"]: hit_dist[r["id"]] for r in rows if r["id"] in hit_dist and r["text_md5"]
    }
    for r in rows:
        r["distance"] = hit_dist.get(r["id"], dist_by_text.get(r["text_md5"]))
    return [PersonSearchHit(**p) for p in group_people(rows)[: max(1, min(limit, 50))]]


@router.get("/candidates/search", response_model=list[CandidateSearchHit])
def search_candidates(
    q: str, limit: int = 10, relative_to: UUID | None = None
) -> list[CandidateSearchHit]:
    """ค้นหาผู้สมัครเก่าด้วยความหมายของข้อความ (ไม่ใช่การจับคำ).

    `relative_to` = ค้นจากหน้าผู้สมัครคนไหน — ไม่คืนตัวเขาเอง และติดป้ายแถวที่เป็นคนเดียวกัน

    ⚠️ ต้องประกาศ **ก่อน** /candidates/{candidate_id} ไม่งั้น FastAPI จะจับคู่เส้นทางนี้
    เป็น candidate_id = "search" แล้วตอบ 404
    """
    if not q.strip():
        raise HTTPException(status_code=400, detail="ต้องระบุคำค้นหา")
    exclude = str(relative_to) if relative_to else None
    try:
        hits = vector_search(q, limit=max(1, min(limit, 50)), exclude_candidate_id=exclude)
    except Exception as exc:  # noqa: BLE001 — โควตา embedding หมด/คีย์ผิด ไม่ควรเป็น 500 เปล่า ๆ
        log.exception("ค้นหาเชิงความหมายล้มเหลว: %s", exc)
        raise HTTPException(status_code=503, detail="ระบบค้นหาไม่พร้อมใช้งานชั่วคราว") from exc
    if exclude:
        hits = _mark_same_person(exclude, hits)
    return [CandidateSearchHit(**h) for h in hits]


@router.get(
    "/candidates/{candidate_id}/photo",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}, 404: {}},
)
def get_candidate_photo(candidate_id: UUID) -> Response:
    """ไบต์รูปโปรไฟล์ที่ดึงไว้ตอนรับไฟล์ — 404 = ไม่มีรูป (หน้าเว็บกลับไปใช้ตัวอักษรย่อ).

    **ไม่ดูสวิตช์ screening_photos โดยตั้งใจ** — ที่นี่แค่เสิร์ฟไฟล์ที่ JWT คุมอยู่แล้ว
    หน้าเว็บเป็นฝ่ายตัดสินว่าจะขอดูไหม เพราะหน้าทะเบียนพนักงานต้องเห็นรูปเสมอ
    ส่วนหน้าคัดกรองขอเฉพาะตอนสวิตช์เปิด

    no-store: รูปคือข้อมูลส่วนบุคคล ไม่ให้เบราว์เซอร์หรือพร็อกซีเก็บไว้ในแคช
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT image_bytes, content_type FROM candidate_photos WHERE candidate_id = %s",
            (str(candidate_id),),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่มีรูปของผู้สมัครคนนี้")
    return Response(
        content=bytes(row["image_bytes"]),
        media_type=row["content_type"],
        headers={"Cache-Control": "private, no-store"},
    )


@router.get(
    "/candidates/{candidate_id}/resume.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}, 404: {}},
)
def get_resume_file(candidate_id: UUID) -> Response:
    """ไฟล์เรซูเม่ PDF ต้นฉบับ — 404 = ไม่มีไฟล์ (ผู้สมัครที่เข้ามาก่อนเริ่มเก็บไฟล์).

    ไฟล์มาจากคนนอก จึงเสิร์ฟแบบที่ให้เบราว์เซอร์เปิดด้วยตัวดู PDF ของมันเอง:
    - Content-Type ตายตัวเป็น application/pdf + nosniff — ห้ามเบราว์เซอร์เดาเป็น HTML
    - inline + ชื่อไฟล์แบบ RFC 5987 (ชื่อไทยได้) — เปิดในแท็บ ไม่บังคับดาวน์โหลด
    - no-store — ข้อมูลส่วนบุคคล ไม่ให้เบราว์เซอร์/พร็อกซีเก็บไว้ในแคช
    หน้าเว็บ fetch พร้อม JWT แล้วเปิดเป็น blob ในแท็บใหม่ ไม่ฝังลงในหน้าของเรา
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT pdf_bytes, filename FROM candidate_files WHERE candidate_id = %s",
            (str(candidate_id),),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่มีไฟล์ต้นฉบับของผู้สมัครคนนี้")
    name = quote(row["filename"] or "resume.pdf")
    return Response(
        content=bytes(row["pdf_bytes"]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=\"resume.pdf\"; filename*=UTF-8''{name}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


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
                   e.similar_candidates, e.bias_revision, e.skill_evidence,
                   e.email_draft_edited, e.email_draft_edited_at,
                   e.score_explanation, e.confidence, (e.id IS NOT NULL) AS has_eval,
                   e.created_at AS evaluated_at,
                   EXISTS (SELECT 1 FROM candidate_files cf WHERE cf.candidate_id = c.id)
                       AS has_resume_file,
                   emp.id AS employee_id, emp.hired_at, hd.decision AS hr_decision,
                   hd.notes AS hr_notes, hd.updated_at AS hr_decided_at,
                   e.rescored_from, e.rescored_at,
                   q.status AS queue_status,
                   -- CASE จำเป็น: to_jsonb(io) บน LEFT JOIN ที่ไม่แมตช์คืน
                   -- {"candidate_id": null, ...} ไม่ใช่ NULL แล้ว Pydantic จะเจอ
                   -- result=None ซึ่งเป็นฟิลด์บังคับ กลายเป็น 500 ของคนที่ยังไม่เคย
                   -- บันทึกผล — คือผู้สมัครเกือบทุกคนในระบบ
                   CASE WHEN io.candidate_id IS NOT NULL THEN to_jsonb(io) END
                       AS interview_outcome,
                   -- CASE เหตุผลเดียวกับ interview_outcome ด้านบน: ไม่มีข้อเสนอ = NULL ไม่ใช่
                   -- {"position": null, ...} ที่ Pydantic จะปฏิเสธเพราะ position บังคับ
                   CASE WHEN jo.candidate_id IS NOT NULL THEN to_jsonb(jo) END
                       AS offer,
                   hs.stage AS stage_row, hs.moved_at AS stage_moved_at,
                   hs.scheduled_at, hs.location,
                   j.jd_audit, j.bias_acknowledgements
            FROM candidates c
            JOIN jobs j ON j.id = c.job_id
            LEFT JOIN evaluations e ON e.candidate_id = c.id
            LEFT JOIN employees emp ON emp.candidate_id = c.id
            LEFT JOIN hr_decisions hd ON hd.candidate_id = c.id
            LEFT JOIN interview_outcome io ON io.candidate_id = c.id
            LEFT JOIN job_offers jo ON jo.candidate_id = c.id
            LEFT JOIN hiring_stage hs ON hs.candidate_id = c.id
            LEFT JOIN LATERAL (
                SELECT status FROM processing_queue pq
                 WHERE pq.candidate_id = c.id AND pq.status = ANY(%s)
                 ORDER BY pq.created_at LIMIT 1
            ) q ON TRUE
            WHERE c.id = %s
            """,
            (list(PENDING_STATUSES), candidate_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบผู้สมัครนี้")
    has_eval = row.pop("has_eval")
    stage_row = row.pop("stage_row")
    # ผลตรวจอคติของตำแหน่ง อ่านสดทุกครั้ง — HR ยืนยันถ้อยคำทีหลัง ผู้สมัครเก่าก็เห็นทันที
    # โดยไม่ต้องแก้ audit_log ในผลประเมินซึ่งเป็นบันทึกของตอนคัดกรอง
    job_bias = bias_view(row.pop("jd_audit"), row.pop("bias_acknowledgements"))
    rescored_at = row.pop("rescored_at")
    if row["similar_candidates"]:
        row["similar_candidates"] = _mark_same_person(candidate_id, row["similar_candidates"])
    active = active_candidates()
    return CandidateDetail(
        **row,
        job_bias=job_bias,
        board_stage=board_stage(
            stage_row, row["employee_id"] is not None, row["hr_decision"], row["fit_score"]
        ),
        graph_status=_effective_graph_status(
            get_graph_status(candidate_id, row["hr_decision"], row["fit_score"]),
            candidate_id, active, row["queue_status"],
        ),
        stalled=_is_stalled(
            candidate_id,
            has_eval,
            row["created_at"],
            active,
            row["queue_status"],
        ),
        score_breakdown=_breakdown_for(row["gap_analysis"], row["fit_score"]),
        needs_recheck=needs_recheck(
            rescored_at, row["rescored_from"], row["fit_score"], row["hr_decided_at"]
        ),
    )


def _breakdown_for(gap: dict | None, fit_score: int | None) -> dict | None:
    """องค์ประกอบคะแนนจาก gap_analysis ที่บันทึกไว้ — ฟังก์ชันบริสุทธิ์ ทดสอบได้ไม่ต้องมี DB.

    เรียก matcher.score_breakdown ซึ่งเป็นสูตรเดียวกับที่ให้คะแนนจริง ไม่ได้คำนวณเองที่นี่
    · matches_stored_score จับแถวที่คะแนนถูกบันทึกด้วยสูตรเก่า (ก่อนเฉลี่ยน้ำหนักใหม่)
    ถ้าไม่บอก หน้าเว็บจะโชว์ผลรวมที่ไม่เท่า fit_score บนการ์ดเดียวกันโดยไม่มีคำอธิบาย
    """
    if not gap:
        return None
    b = score_breakdown(
        gap.get("matched_required") or [],
        gap.get("missing_required") or [],
        gap.get("matched_preferred") or [],
        gap.get("missing_preferred") or [],
    )
    b["matches_stored_score"] = fit_score is not None and round(b["total"]) == fit_score
    return b
