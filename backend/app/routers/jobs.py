"""เราเตอร์ตำแหน่งงาน (Job Description)."""
import logging
import os
import time

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Json

from app.agents.llm import DEFAULT_MODEL
from app.agents.nodes.jd_analyzer import extract_jd
from app.agents.nodes.jd_reviewer import review_jd
from app.agents.runner import active_candidates
from app.agents.models import JDReview
from app.auth import get_current_user
from app.rate_limit import hit_and_check, retry_after_sec
from app.database import get_checkpointer, get_conn
from app.criteria_edit import criteria_warnings, normalize_criteria, rescore_job
from app.job_queue import PENDING_STATUSES
from app.llm_quota import has_room, used_today
from app.schemas import (
    CriteriaIn,
    CriteriaPreviewOut,
    CriteriaSaveOut,
    JDReviewIn,
    JobCreate,
    JobDeleteOut,
    JobListItem,
    JobOut,
    JobStatusUpdate,
)

# คอลัมน์ที่ทุก endpoint คืนเป็น JobOut — รวมไว้ที่เดียวกันเผื่อเพิ่มฟิลด์ทีหลัง
_JOB_COLS = (
    "id, title, raw_text, parsed_criteria, status, closed_at, created_at, "
    "ai_criteria, criteria_edited_at"
)

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
    extraction: dict | None = None
    try:
        requirement, raw_labels = extract_jd(payload.raw_text)
        analyzed = requirement.model_dump()
        # ป้ายดิบต่อคำ — parsed_criteria ถูกจัดฝั่งจากสิ่งนี้ เก็บไว้ให้ทางแก้ข้อ 3 ไม่ต้องเรียก LLM ซ้ำ
        extraction = raw_labels.model_dump()
    except Exception as exc:  # noqa: BLE001 — อย่าให้ endpoint ล้มเพราะ LLM
        log.warning("jd_analyzer ล้มเหลว จะบันทึกงานโดยยังไม่มี parsed_criteria: %s", exc)

    title = (analyzed or {}).get("job_title") or fallback_title
    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO jobs (title, raw_text, parsed_criteria, jd_extraction)
            VALUES (%s, %s, %s, %s)
            RETURNING """
            + _JOB_COLS,
            (
                title,
                payload.raw_text,
                Json(analyzed) if analyzed else None,
                Json(extraction) if extraction else None,
            ),
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


# ---------- HR แก้เกณฑ์ทักษะ ----------
# ที่มาและกติกาอยู่ใน app/criteria_edit.py · ทั้งสามเส้นทางไม่เรียก LLM เลย


def _load_job_for_criteria(conn, job_id: str) -> dict:
    row = conn.execute(
        f"SELECT {_JOB_COLS} FROM jobs WHERE id = %s", (job_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบตำแหน่งงานนี้")
    return row


def _busy_candidates(conn, job_id: str) -> int:
    """จำนวนผู้สมัครของตำแหน่งนี้ที่กราฟกำลังรันหรือมีงานค้างในคิว.

    ต้องกันไว้ เพราะกราฟที่กำลังเดินจะบันทึกคะแนนด้วยเกณฑ์เก่าทับคะแนนที่เพิ่งคำนวณใหม่
    เช็คทั้งทะเบียนในโปรเซสและแถวคิว เพราะทะเบียนหายตอนรีสตาร์ตแต่แถวคิวไม่หาย
    """
    ids = {str(r["id"]) for r in conn.execute(
        "SELECT id FROM candidates WHERE job_id = %s", (job_id,)
    ).fetchall()}
    queued = conn.execute(
        """SELECT count(DISTINCT pq.candidate_id) AS n
             FROM processing_queue pq JOIN candidates c ON c.id = pq.candidate_id
            WHERE c.job_id = %s AND pq.status = ANY(%s)""",
        (job_id, list(PENDING_STATUSES)),
    ).fetchone()["n"]
    return max(len(ids & active_candidates()), queued)


def _preview(conn, job_id: str, payload: CriteriaIn, apply: bool) -> dict:
    clean = normalize_criteria(payload.required_skills, payload.preferred_skills)
    req, pref = clean["required_skills"], clean["preferred_skills"]
    return {
        "required_skills": req,
        "preferred_skills": pref,
        "dropped": clean["dropped"],
        "warnings": criteria_warnings(req, pref),
        "impact": rescore_job(conn, job_id, req, pref, apply=apply),
    }


@router.post("/{job_id}/criteria/preview", response_model=CriteriaPreviewOut)
def preview_criteria(job_id: str, payload: CriteriaIn) -> CriteriaPreviewOut:
    """ผลกระทบของเกณฑ์ใหม่ต่อผู้สมัครทุกคน — **ไม่เขียนอะไรเลย** ให้ HR ดูก่อนกดบันทึก."""
    with get_conn() as conn:
        _load_job_for_criteria(conn, job_id)
        result = _preview(conn, job_id, payload, apply=False)
        conn.rollback()  # ไม่มีอะไรให้ย้อน แต่ปิดทรานแซกชันอ่านให้ชัดว่าไม่ได้ตั้งใจเขียน
    return CriteriaPreviewOut(**result)


def _save_criteria(job_id: str, payload: CriteriaIn, reset: bool = False) -> CriteriaSaveOut:
    """บันทึกเกณฑ์ + คำนวณคะแนนคนเดิมใหม่ในทรานแซกชันเดียว — ล้มกลางทางต้องไม่เหลือสภาพ
    ที่เกณฑ์เปลี่ยนแล้วแต่คะแนนยังเป็นของเกณฑ์เก่า (หรือกลับกัน)."""
    with get_conn() as conn:
        job = _load_job_for_criteria(conn, job_id)
        busy = _busy_candidates(conn, job_id)
        if busy:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"มีผู้สมัคร {busy} คนของตำแหน่งนี้กำลังวิเคราะห์หรือรอคิวอยู่ — "
                    "รอให้เสร็จก่อนแล้วค่อยแก้เกณฑ์ ไม่งั้นคะแนนของเกณฑ์เก่าจะเขียนทับ"
                ),
            )
        result = _preview(conn, job_id, payload, apply=True)
        # parsed_criteria เป็น NULL ได้ (AI อ่านไม่สำเร็จตอนสร้าง) — เติมจากผลอ่านใหม่ถ้ามี
        # แล้วเติมค่าตั้งต้นของฟิลด์อื่นให้ครบรูป JobRequirement ที่กราฟและหน้าเว็บคาดหวัง
        current = dict(job["parsed_criteria"] or job["ai_criteria"] or {})
        current.setdefault("job_title", job["title"])
        current.setdefault("min_experience_years", 0)
        current.setdefault("education", "")
        # เก็บของที่ AI ดึงไว้ครั้งแรกเท่านั้น — แก้รอบที่สองต้องไม่ทับด้วยฉบับของ HR
        # ⚠️ ต้องเป็นสำเนาแยก ไม่ใช่ `or current` ตรง ๆ: ถ้าเป็น dict ตัวเดียวกัน บรรทัดถัดไป
        # ที่แก้ current จะเขียนทับของ AI ไปด้วย แล้วปุ่มคืนค่าจะคืนฉบับของ HR (เทสจับได้)
        ai = job["ai_criteria"] or dict(job["parsed_criteria"] or {})
        # แทนแค่สองรายการ คง job_title / min_experience_years / education ไว้ตามเดิม
        current["required_skills"] = result["required_skills"]
        current["preferred_skills"] = result["preferred_skills"]
        row = conn.execute(
            f"""
            UPDATE jobs
               SET parsed_criteria = %s, ai_criteria = %s,
                   -- คืนค่าของ AI = กลับเป็น "ยังไม่เคยแก้" ไม่ใช่ "HR แก้เมื่อกี้"
                   criteria_edited_at = CASE WHEN %s THEN NULL ELSE now() END
             WHERE id = %s
            RETURNING {_JOB_COLS}
            """,
            (Json(current), Json(ai), reset, job_id),
        ).fetchone()
        conn.commit()
    changed = sum(1 for i in result["impact"] if i["old_score"] != i["new_score"])
    log.info("HR แก้เกณฑ์ของตำแหน่ง %s — คะแนนเปลี่ยน %s คน", job_id, changed)
    return CriteriaSaveOut(**result, job=JobOut(**row))


@router.put("/{job_id}/criteria", response_model=CriteriaSaveOut)
def save_criteria(job_id: str, payload: CriteriaIn) -> CriteriaSaveOut:
    """HR แก้รายการทักษะ แล้วคำนวณคะแนนคนเดิมใหม่ทันที (ไม่เรียก LLM ไม่เดินกราฟใหม่).

    คนที่แบนด์เปลี่ยนจะขึ้นป้าย "ตรวจอีกครั้ง" ให้ HR ตัดสินเอง — ระบบไม่ลบร่างอีเมล
    ไม่สร้างคำถามใหม่ และไม่แตะคำตัดสินเดิม
    """
    return _save_criteria(job_id, payload)


@router.post("/{job_id}/criteria/reset", response_model=CriteriaSaveOut)
def reset_criteria(job_id: str) -> CriteriaSaveOut:
    """คืนรายการทักษะตามที่ AI ดึงไว้ — เดินเส้นทางเดียวกับการบันทึก (คำนวณคะแนนใหม่ด้วย)."""
    with get_conn() as conn:
        job = _load_job_for_criteria(conn, job_id)
    ai = job["ai_criteria"]
    if not ai:
        raise HTTPException(status_code=409, detail="ตำแหน่งนี้ยังไม่เคยแก้เกณฑ์ ไม่มีอะไรให้คืนค่า")
    return _save_criteria(
        job_id,
        CriteriaIn(
            required_skills=ai.get("required_skills") or [],
            preferred_skills=ai.get("preferred_skills") or [],
        ),
        reset=True,
    )


# เพดานการกด "ให้ AI อ่านประกาศใหม่" ต่อผู้ใช้ต่อนาที — กันกดรัวจนเปลืองโควตา ไม่ใช่กันโจมตี
REANALYZE_MAX_PER_MIN = int(os.getenv("REANALYZE_MAX_PER_MIN", "5"))
_reanalyze_hits: dict[str, list[float]] = {}
# ต้องผ่าน CriteriaIn เหมือนที่ HR พิมพ์เอง — ประกาศยาวอาจให้รายการยาวกว่าเพดานของ schema
_MAX_SKILLS, _MAX_SKILL_CHARS = 50, 100


@router.post("/{job_id}/criteria/reanalyze", response_model=CriteriaPreviewOut)
def reanalyze_criteria(job_id: str, user: str = Depends(get_current_user)) -> CriteriaPreviewOut:
    """ให้ jd_analyzer อ่านประกาศของตำแหน่งนี้ใหม่ แล้วคืนผลแบบพรีวิว — **ไม่แตะคะแนนและเกณฑ์ที่ใช้อยู่**.

    สำหรับตำแหน่งที่สร้างก่อน jd_analyzer แบบติดป้าย (memory-bank/06) หรือที่ AI อ่านไม่สำเร็จ
    ตอนสร้าง · HR ตรวจผลในหน้าต่างแก้เกณฑ์ แล้วกดบันทึกผ่าน PUT /criteria เหมือนแก้เอง
    ผู้สมัครเดิม คำตัดสิน และอีเมลที่ส่งแล้วจึงอยู่ครบ ต่างจากการลบตำแหน่งแล้วสร้างใหม่

    บันทึกทันที (ผู้ใช้ตัดสิน 2026-09-19) เฉพาะสองคอลัมน์ที่ไม่ใช่เกณฑ์ที่ใช้คิดคะแนน:
    - jd_extraction = ป้ายชุดใหม่ ไว้ให้ทางแก้ข้อ 3
    - ai_criteria   = ผลอ่านล่าสุด ให้ "คืนค่าตามที่ AI ดึง" คืนผลนี้ ไม่ใช่ผลเก่าที่อ่านผิด

    ใช้ 1 chat call · ไม่ retry เพราะ HR นั่งรอ · 429 เมื่อกดถี่หรือโควตาวันนี้เต็ม · 502 เมื่อ AI ล้ม
    """
    with get_conn() as conn:
        job = _load_job_for_criteria(conn, job_id)

    now = time.time()
    if not hit_and_check(_reanalyze_hits, user, now, REANALYZE_MAX_PER_MIN, _JD_REVIEW_WINDOW_SEC):
        wait = retry_after_sec(_reanalyze_hits, user, now, _JD_REVIEW_WINDOW_SEC)
        raise HTTPException(
            status_code=429,
            detail=f"ให้ AI อ่านประกาศใหม่ได้ไม่เกิน {REANALYZE_MAX_PER_MIN} ครั้งต่อนาที — ลองใหม่ในอีก {wait} วินาที",
        )
    if not has_room(used_today(DEFAULT_MODEL), 1):
        raise HTTPException(
            status_code=429,
            detail="โควตา AI ของวันนี้เต็มแล้ว — ลองใหม่พรุ่งนี้ หรือแก้เกณฑ์เองในหน้าต่างนี้ได้เลย",
        )

    try:
        requirement, labels = extract_jd(job["raw_text"], once=True)
    except Exception as exc:  # noqa: BLE001 — โควตา/เครือข่าย/คำตอบผิดรูป ไม่ควรเป็น 500 เปล่า ๆ
        log.exception("อ่านประกาศใหม่ไม่สำเร็จ job=%s: %s", job_id, exc)
        raise HTTPException(status_code=502, detail="AI อ่านประกาศไม่สำเร็จ ลองใหม่อีกครั้ง") from exc

    payload = CriteriaIn(
        required_skills=[s[:_MAX_SKILL_CHARS] for s in requirement.required_skills[:_MAX_SKILLS]],
        preferred_skills=[s[:_MAX_SKILL_CHARS] for s in requirement.preferred_skills[:_MAX_SKILLS]],
    )
    with get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET jd_extraction = %s, ai_criteria = %s WHERE id = %s",
            (Json(labels.model_dump()), Json(requirement.model_dump()), job_id),
        )
        result = _preview(conn, job_id, payload, apply=False)
        conn.commit()
    log.info("AI อ่านประกาศใหม่ job=%s — ต้องมี %s ข้อ อยากได้ %s ข้อ", job_id,
             len(result["required_skills"]), len(result["preferred_skills"]))
    return CriteriaPreviewOut(**result)


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
